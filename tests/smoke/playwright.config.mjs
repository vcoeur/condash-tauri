import { defineConfig } from '@playwright/test';

// Port comes in from `make smoke` so CI and local runs match.
const port = process.env.CONDASH_SMOKE_PORT || '3911';
const fixture = process.env.CONDASH_SMOKE_FIXTURE;
if (!fixture) {
    throw new Error(
        'CONDASH_SMOKE_FIXTURE is required (path to a conception tree). Run via `make smoke`.',
    );
}

const cargoBin = process.env.CARGO || 'cargo';

export default defineConfig({
    testDir: '.',
    timeout: 60_000,
    fullyParallel: false,
    workers: 1,
    reporter: 'list',
    use: {
        baseURL: `http://127.0.0.1:${port}`,
        trace: 'retain-on-failure',
    },
    webServer: {
        // condash-serve speaks the same HTTP surface the Tauri host uses,
        // so we get to exercise the dispatcher + SSE loop without the
        // GUI's libwebkit dependency.
        command: `${cargoBin} run -q --bin condash-serve`,
        url: `http://127.0.0.1:${port}/`,
        timeout: 180_000,
        reuseExistingServer: false,
        stdout: 'pipe',
        stderr: 'pipe',
        env: {
            CONDASH_CONCEPTION_PATH: fixture,
            CONDASH_PORT: port,
        },
    },
});
