//! Static SVG icon strings — Rust port of `render.py::_ICON_SVGS`.
//!
//! Every icon appears as a raw `<svg>…</svg>` string so the template
//! engine can emit it with `{{ icons.foo | safe }}`. Kept in a single
//! module to mirror Python's dict; the enum is constructed once per
//! render and serialised into the minijinja `Value` tree.

/// Named SVG icons referenced by the dashboard templates.
///
/// Field names mirror the Python dict keys so the templates — which
/// live alongside the wheel — can be reused unchanged.
pub struct Icons;

macro_rules! def_icons {
    ($( $field:ident = $value:expr ; )+) => {
        impl Icons {
            $(
                #[allow(non_upper_case_globals)]
                pub const $field: &'static str = $value;
            )+
        }

        /// Serialize the icon constants into a minijinja value under the
        /// same field names the Jinja templates use (`{{ icons.folder }}`,
        /// etc.). Kept as a function rather than a struct so adding a
        /// new icon doesn't force a breaking change in consumers.
        pub fn icons_value() -> minijinja::Value {
            let ctx = minijinja::context! {
                $(
                    $field => minijinja::Value::from(Icons::$field),
                )+
            };
            ctx
        }
    };
}

def_icons! {
    main_ide = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"15\" height=\"15\" fill=\"none\" ",
        "stroke=\"currentColor\" stroke-width=\"2.2\" stroke-linecap=\"round\" ",
        "stroke-linejoin=\"round\" aria-hidden=\"true\">",
        "<rect x=\"3\" y=\"4\" width=\"18\" height=\"16\" rx=\"2\"/>",
        "<line x1=\"3\" y1=\"9\" x2=\"21\" y2=\"9\"/>",
        "<line x1=\"7\" y1=\"14\" x2=\"13\" y2=\"14\"/>",
        "<line x1=\"7\" y1=\"17\" x2=\"11\" y2=\"17\"/></svg>",
    );
    secondary_ide = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"15\" height=\"15\" fill=\"none\" ",
        "stroke=\"currentColor\" stroke-width=\"2.4\" stroke-linecap=\"round\" ",
        "stroke-linejoin=\"round\" aria-hidden=\"true\">",
        "<polyline points=\"16 18 22 12 16 6\"/>",
        "<polyline points=\"8 6 2 12 8 18\"/></svg>",
    );
    terminal = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"15\" height=\"15\" fill=\"none\" ",
        "stroke=\"currentColor\" stroke-width=\"2.4\" stroke-linecap=\"round\" ",
        "stroke-linejoin=\"round\" aria-hidden=\"true\">",
        "<polyline points=\"4 17 10 11 4 5\"/>",
        "<line x1=\"12\" y1=\"19\" x2=\"20\" y2=\"19\"/></svg>",
    );
    integrated_terminal = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"15\" height=\"15\" fill=\"none\" ",
        "stroke=\"currentColor\" stroke-width=\"2.2\" stroke-linecap=\"round\" ",
        "stroke-linejoin=\"round\" aria-hidden=\"true\">",
        "<rect x=\"3\" y=\"4\" width=\"18\" height=\"16\" rx=\"2\"/>",
        "<polyline points=\"7 11 10 14 7 17\"/>",
        "<line x1=\"12\" y1=\"17\" x2=\"16\" y2=\"17\"/></svg>",
    );
    work_on = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"15\" height=\"15\" fill=\"none\" ",
        "stroke=\"currentColor\" stroke-width=\"2.2\" stroke-linecap=\"round\" ",
        "stroke-linejoin=\"round\" aria-hidden=\"true\">",
        "<rect x=\"3\" y=\"4\" width=\"18\" height=\"16\" rx=\"2\"/>",
        "<polygon points=\"10 9 16 12 10 15\" fill=\"currentColor\" stroke=\"none\"/></svg>",
    );
    runner_run = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"15\" height=\"15\" fill=\"currentColor\" ",
        "aria-hidden=\"true\">",
        "<polygon points=\"7 5 19 12 7 19\"/></svg>",
    );
    runner_stop = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"15\" height=\"15\" fill=\"currentColor\" ",
        "aria-hidden=\"true\">",
        "<rect x=\"6\" y=\"6\" width=\"12\" height=\"12\" rx=\"1\"/></svg>",
    );
    runner_force_stop = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"15\" height=\"15\" fill=\"currentColor\" ",
        "aria-hidden=\"true\">",
        "<polygon points=\"13 2 4 14 11 14 10 22 20 9 13 9\"/></svg>",
    );
    runner_jump = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"13\" height=\"13\" fill=\"none\" ",
        "stroke=\"currentColor\" stroke-width=\"2.4\" stroke-linecap=\"round\" ",
        "stroke-linejoin=\"round\" aria-hidden=\"true\">",
        "<polyline points=\"6 9 12 15 18 9\"/></svg>",
    );
    runner_collapse = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"13\" height=\"13\" fill=\"none\" ",
        "stroke=\"currentColor\" stroke-width=\"2.4\" stroke-linecap=\"round\" ",
        "stroke-linejoin=\"round\" aria-hidden=\"true\">",
        "<polyline points=\"6 15 12 9 18 15\"/></svg>",
    );
    runner_popout = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"14\" height=\"14\" fill=\"none\" ",
        "stroke=\"currentColor\" stroke-width=\"2.2\" stroke-linecap=\"round\" ",
        "stroke-linejoin=\"round\" aria-hidden=\"true\">",
        "<path d=\"M14 4h6v6\"/>",
        "<line x1=\"10\" y1=\"14\" x2=\"20\" y2=\"4\"/>",
        "<path d=\"M20 14v6H4V4h6\"/></svg>",
    );
    folder = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"15\" height=\"15\" fill=\"none\" ",
        "stroke=\"currentColor\" stroke-width=\"2.2\" stroke-linecap=\"round\" ",
        "stroke-linejoin=\"round\" aria-hidden=\"true\">",
        "<path d=\"M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z\"/></svg>",
    );
    open_caret = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"10\" height=\"10\" fill=\"none\" ",
        "stroke=\"currentColor\" stroke-width=\"3\" stroke-linecap=\"round\" ",
        "stroke-linejoin=\"round\" aria-hidden=\"true\">",
        "<polyline points=\"6 9 12 15 18 9\"/></svg>",
    );
    peer_jump = concat!(
        "<svg viewBox=\"0 0 24 24\" width=\"12\" height=\"12\" fill=\"none\" ",
        "stroke=\"currentColor\" stroke-width=\"2.4\" stroke-linecap=\"round\" ",
        "stroke-linejoin=\"round\" aria-hidden=\"true\">",
        "<line x1=\"7\" y1=\"17\" x2=\"17\" y2=\"7\"/>",
        "<polyline points=\"7 7 17 7 17 17\"/></svg>",
    );
}
