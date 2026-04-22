// Prevents additional console window on Windows in release. Does not
// affect Linux/macOS.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // Strip AppImageKit AppRun's env-var injections before anything else
    // runs — any thread spawn or Command::new after this point would
    // inherit the contaminated env. See env_hygiene.rs for the full
    // rationale.
    #[cfg(target_os = "linux")]
    condash_lib::env_hygiene::scrub_appimage_leaks();

    // Linux rendering hygiene — both fixes must run before any GTK
    // init, i.e. before tauri::Builder touches wry.
    #[cfg(target_os = "linux")]
    {
        // The AppImage's `linuxdeploy-plugin-gtk` AppRun hook exports
        // GDK_BACKEND=x11 for portability across distros that might
        // not have a working Wayland stack. On GNOME / KDE Wayland
        // sessions that forces condash through XWayland, which is the
        // real source of blurry text on fractional-scaling compositors
        // — not the DMA-BUF renderer. When a Wayland display is in
        // fact available, drop the override so GDK picks Wayland
        // natively and the window renders crisply. Leave the value
        // alone on pure-X11 sessions and when the user set it
        // themselves.
        if std::env::var_os("WAYLAND_DISPLAY").is_some()
            && std::env::var("GDK_BACKEND").as_deref() == Ok("x11")
        {
            std::env::remove_var("GDK_BACKEND");
        }
        // Secondary belt-and-suspenders: WebKitGTK 2.42+ enables a
        // DMA-BUF renderer that can still go blurry on some integer-
        // scale mutter setups even on the native Wayland path. Respect
        // an existing value so power users can re-enable it.
        if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
            std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
        }
    }

    condash_lib::run()
}
