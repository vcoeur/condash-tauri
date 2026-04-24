// Dashboard bundle entry. Imports run top-to-bottom: dashboard-main
// installs globals first, then the CM6 init bridge (window.CondashCM →
// window.__cm6) and the PDF viewer surface, which depend on those
// globals.
import "./dashboard-main.js";
import "./cm6-init.js";
import "./pdf-viewer.js";
