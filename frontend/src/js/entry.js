// Dashboard bundle entry — F3/F4 of condash-frontend-split. Imports run
// top-to-bottom: dashboard-main installs globals first, then the CM6 mount
// wiring + markdown-preview surface which depend on those globals.
import "./dashboard-main.js";
import "./cm6-mount.js";
import "./markdown-preview.js";
