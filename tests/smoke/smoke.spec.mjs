// End-to-end smoke against condash-serve. One spec, six checks — boots
// the Rust HTTP surface, opens the dashboard, exercises the SSE → htmx
// loop and the data-action dispatcher, and asserts the inline-handler
// CI guard's invariant at runtime so a regression slipping past the
// lint step still fails CI.
//
// Audit: 2026-04-25-condash-architecture-audit/notes/07 Commit 12.
// Ships with the C12 cut of the architecture-hardening-finish project.

import { test, expect } from '@playwright/test';
import { promises as fs } from 'node:fs';
import path from 'node:path';

const FIXTURE = process.env.CONDASH_SMOKE_FIXTURE;

test('dashboard renders a card grid + reacts to fs events + dispatches actions', async ({ page }) => {
    const consoleEvents = [];
    page.on('console', (msg) => consoleEvents.push({ type: msg.type(), text: msg.text() }));

    await page.goto('/');

    // 1. The cards container lands and at least one project card renders.
    const cards = page.locator('#cards');
    await expect(cards).toBeVisible();
    await expect(cards.locator('.card').first()).toBeVisible();
    const initialCardCount = await cards.locator('.card').count();
    expect(initialCardCount).toBeGreaterThan(0);

    // 2. Touching a README publishes the named `sse:projects` event and
    //    the cards container re-renders. We hook htmx's swap signal so
    //    we don't have to compare innerHTML for staleness.
    const swapPromise = page.evaluate(
        () =>
            new Promise((resolve) => {
                const h = () => {
                    document.body.removeEventListener('htmx:afterSwap', h);
                    resolve(true);
                };
                document.body.addEventListener('htmx:afterSwap', h);
                setTimeout(() => resolve(false), 4000);
            }),
    );
    const someReadme = await firstReadme(FIXTURE);
    const buf = await fs.readFile(someReadme);
    await fs.writeFile(someReadme, buf);  // bump mtime, content unchanged
    expect(await swapPromise).toBe(true);

    // 3. Click an existing data-action="toggle-card" button — assert the
    //    .collapsed class flips off (cards render collapsed by default).
    const firstCard = cards.locator('.card').first();
    await expect(firstCard).toHaveClass(/collapsed/);
    await firstCard.locator('[data-action="toggle-card"]').first().click();
    await expect(firstCard).not.toHaveClass(/collapsed/);

    // 4. Synthesize a click on an unknown data-action; assert
    //    action-dispatch.js logs a console.warn (R-07 from PR #51).
    consoleEvents.length = 0;
    await page.evaluate(() => {
        const probe = document.createElement('button');
        probe.setAttribute('data-action', 'this-does-not-exist');
        probe.id = '__smoke-unknown-action';
        document.body.appendChild(probe);
        probe.click();
    });
    const sawWarn = consoleEvents.some(
        (e) => e.type === 'warning' && /data-action with no handler.*this-does-not-exist/i.test(e.text),
    );
    expect(sawWarn, `no warn for unknown data-action; saw ${JSON.stringify(consoleEvents)}`).toBe(true);

    // 5. The PR #51 inline-handler guard is a `grep` over source files;
    //    assert at runtime that the served DOM holds zero inline named
    //    `on(input|submit|change|...)=` attributes too — a regression
    //    that bypassed the lint (e.g. from a server-side template) would
    //    still fail here.
    const inlineHits = await page.evaluate(() => {
        const re = /^on(input|submit|change|pointerdown|mousedown|dblclick|keydown)$/;
        const out = [];
        document.querySelectorAll('*').forEach((el) => {
            for (const a of el.attributes) {
                if (re.test(a.name)) out.push({ tag: el.tagName, name: a.name, value: a.value });
            }
        });
        return out;
    });
    expect(inlineHits, 'inline named on*= attrs leaked into the DOM').toEqual([]);

    // 6. Companion to step 5: pre-PR-#51 the bundle exposed dozens of
    //    handlers as window globals (Object.assign(window, …)). Confirm
    //    none of the names the old inline handlers used are still bound
    //    — if the dispatcher migration partially regressed, one of these
    //    globals would reappear and the matching `on*=` attr would
    //    silently start working again, hiding a regression that the
    //    DOM scan above would otherwise flag.
    const leakedGlobals = await page.evaluate(() => {
        const names = [
            'filterKnowledge', 'noteSearchRun', '_setDirty', 'saveConfig',
            'submitNewItem', 'stepPointerDown', 'termDragStart',
            'termSplitStart', 'startRenameNote', 'addStep',
        ];
        return names.filter((n) => typeof window[n] !== 'undefined');
    });
    expect(leakedGlobals, 'old inline-handler names leaked back onto window').toEqual([]);
});

// Locate the first README under projects/ in the fixture so we can
// touch it to trigger the SSE pulse.
async function firstReadme(root) {
    async function walk(dir) {
        const entries = await fs.readdir(dir, { withFileTypes: true });
        entries.sort((a, b) => a.name.localeCompare(b.name));
        for (const e of entries) {
            if (e.name.startsWith('.')) continue;
            const full = path.join(dir, e.name);
            if (e.isDirectory()) {
                const found = await walk(full);
                if (found) return found;
            } else if (e.name === 'README.md') {
                return full;
            }
        }
        return null;
    }
    const found = await walk(path.join(root, 'projects'));
    if (!found) throw new Error(`no README under ${root}/projects`);
    return found;
}
