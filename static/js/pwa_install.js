(function () {
    const installButtons = Array.from(document.querySelectorAll("#pwaInstallBtn, #pwaInstallBtnMobile"));
    if (installButtons.length === 0) {
        return;
    }

    let deferredPrompt = null;
    let lastInstallDiagnostics = null;
    const userAgent = navigator.userAgent || "";
    const isIos = /iphone|ipad|ipod/i.test(userAgent);
    const isAndroid = /android/i.test(userAgent);
    const isStandalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;

    function setStandaloneClasses() {
        if (!isStandalone) {
            return;
        }
        document.body.classList.add("pp-standalone");
        if (isIos) {
            document.body.classList.add("pp-standalone-ios");
        } else if (isAndroid) {
            document.body.classList.add("pp-standalone-android");
        } else {
            document.body.classList.add("pp-standalone-desktop");
        }
    }

    function updateInstallButtons(state) {
        installButtons.forEach((button) => {
            button.style.display = state === "show" ? "inline-flex" : "none";
            button.disabled = state !== "show";
            button.setAttribute("aria-disabled", state === "show" ? "false" : "true");
            button.title = state === "show" ? "Install PressureProof" : "PressureProof is already installed";
        });
    }

    function showInstallButton() {
        updateInstallButtons("show");
    }

    function hideInstallButton() {
        updateInstallButtons("hide");
    }

    function showToast(message) {
        const existing = document.getElementById("ppInstallToast");
        if (existing) {
            existing.remove();
        }

        const container = document.createElement("div");
        container.className = "toast-container position-fixed bottom-0 end-0 p-3";
        container.style.zIndex = "2000";

        const toastEl = document.createElement("div");
        toastEl.id = "ppInstallToast";
        toastEl.className = "toast text-bg-dark border-0";
        toastEl.setAttribute("role", "status");
        toastEl.setAttribute("aria-live", "polite");
        toastEl.setAttribute("aria-atomic", "true");
        toastEl.innerHTML = `<div class="d-flex"><div class="toast-body">${message}</div></div>`;

        container.appendChild(toastEl);
        document.body.appendChild(container);

        if (window.bootstrap && window.bootstrap.Toast) {
            const toast = new window.bootstrap.Toast(toastEl, { delay: 3500 });
            toast.show();
        } else {
            toastEl.classList.add("show");
            setTimeout(() => {
                toastEl.classList.remove("show");
            }, 3500);
        }
    }

    function buildIosModal() {
        if (document.getElementById("ppIosInstallModal")) {
            return;
        }

        const modal = document.createElement("div");
        modal.className = "modal fade";
        modal.id = "ppIosInstallModal";
        modal.tabIndex = -1;
        modal.setAttribute("aria-hidden", "true");

        modal.innerHTML = "" +
            "<div class=\"modal-dialog modal-dialog-centered\">" +
            "<div class=\"modal-content\">" +
            "<div class=\"modal-header\">" +
            "<h5 class=\"modal-title\">Install PressureProof</h5>" +
            "<button type=\"button\" class=\"btn-close\" data-bs-dismiss=\"modal\" aria-label=\"Close\"></button>" +
            "</div>" +
            "<div class=\"modal-body\">" +
            "<p class=\"mb-3\">iPhone and iPad use Safari's Share menu for install.</p>" +
            "<ol class=\"mb-3\">" +
            "<li class=\"mb-2\">Tap the Share button in Safari.</li>" +
            "<li class=\"mb-2\">Scroll and tap Add to Home Screen.</li>" +
            "<li class=\"mb-0\">Tap Add in the top right corner.</li>" +
            "</ol>" +
            "<p class=\"small text-secondary mb-0\">Chrome on iPhone cannot show the native install prompt. Open this page in Safari first.</p>" +
            "</div>" +
            "</div>" +
            "</div>";

        document.body.appendChild(modal);
    }

    function openIosModal() {
        buildIosModal();
        const modalEl = document.getElementById("ppIosInstallModal");
        if (modalEl && window.bootstrap && window.bootstrap.Modal) {
            const modal = new window.bootstrap.Modal(modalEl);
            modal.show();
        }
    }

    function buildDiagnosticsModal() {
        if (document.getElementById("ppInstallDiagnosticsModal")) {
            return;
        }

        const modal = document.createElement("div");
        modal.className = "modal fade";
        modal.id = "ppInstallDiagnosticsModal";
        modal.tabIndex = -1;
        modal.setAttribute("aria-hidden", "true");
        modal.innerHTML = "" +
            "<div class=\"modal-dialog modal-dialog-centered modal-lg\">" +
            "<div class=\"modal-content\">" +
            "<div class=\"modal-header\">" +
            "<h5 class=\"modal-title\">Install diagnostics</h5>" +
            "<button type=\"button\" class=\"btn-close\" data-bs-dismiss=\"modal\" aria-label=\"Close\"></button>" +
            "</div>" +
            "<div class=\"modal-body\">" +
            "<p class=\"mb-3\">Your browser is not exposing the native install prompt yet. These checks help pinpoint why.</p>" +
            "<div id=\"ppInstallDiagnosticsBody\" class=\"small\"></div>" +
            "</div>" +
            "<div class=\"modal-footer\">" +
            "<button type=\"button\" class=\"btn btn-outline-secondary\" data-bs-dismiss=\"modal\">Close</button>" +
            "</div>" +
            "</div>" +
            "</div>";

        document.body.appendChild(modal);
    }

    function renderDiagnosticsList(diagnostics) {
        const target = document.getElementById("ppInstallDiagnosticsBody");
        if (!target || !diagnostics) {
            return;
        }

        const rows = [
            ["Secure context", diagnostics.isSecureContext ? "Yes" : "No"],
            ["Service worker supported", diagnostics.supportsServiceWorker ? "Yes" : "No"],
            ["Service worker controlling page", diagnostics.hasController ? "Yes" : "No"],
            ["Manifest link present", diagnostics.hasManifestLink ? "Yes" : "No"],
            ["Manifest fetch OK", diagnostics.manifestOk ? "Yes" : "No"],
            ["beforeinstallprompt fired", diagnostics.beforeInstallPromptSeen ? "Yes" : "No"],
            ["Standalone mode", diagnostics.isStandalone ? "Yes" : "No"],
            ["Platform", diagnostics.platform || "Unknown"],
            ["User agent", diagnostics.userAgent || "Unknown"],
        ];

        target.innerHTML = rows.map(([label, value]) => (
            `<div class="d-flex justify-content-between border-bottom py-2"><span class="text-secondary">${label}</span><span class="fw-semibold">${value}</span></div>`
        )).join("");
    }

    async function collectDiagnostics() {
        const manifestLink = document.querySelector('link[rel="manifest"]');
        let manifestOk = false;

        if (manifestLink && manifestLink.href) {
            try {
                const response = await fetch(manifestLink.href, { cache: "no-store" });
                manifestOk = response.ok;
            } catch (error) {
                manifestOk = false;
            }
        }

        let hasController = false;
        try {
            if ("serviceWorker" in navigator) {
                const registration = await navigator.serviceWorker.getRegistration("/");
                hasController = Boolean(navigator.serviceWorker.controller || (registration && registration.active));
            }
        } catch (error) {
            hasController = Boolean(navigator.serviceWorker && navigator.serviceWorker.controller);
        }

        return {
            isSecureContext: window.isSecureContext === true,
            supportsServiceWorker: "serviceWorker" in navigator,
            hasController: hasController,
            hasManifestLink: Boolean(manifestLink),
            manifestOk: manifestOk,
            beforeInstallPromptSeen: Boolean(deferredPrompt),
            isStandalone: isStandalone,
            platform: isIos ? "iOS" : (isAndroid ? "Android" : "Desktop"),
            userAgent: userAgent,
        };
    }

    async function openDiagnosticsModal() {
        buildDiagnosticsModal();
        lastInstallDiagnostics = await collectDiagnostics();
        renderDiagnosticsList(lastInstallDiagnostics);

        const modalEl = document.getElementById("ppInstallDiagnosticsModal");
        if (modalEl && window.bootstrap && window.bootstrap.Modal) {
            const modal = new window.bootstrap.Modal(modalEl);
            modal.show();
        }
    }

    async function attemptInstall() {
        if (isStandalone) {
            hideInstallButton();
            return;
        }

        if (deferredPrompt) {
            deferredPrompt.prompt();
            const choice = await deferredPrompt.userChoice;
            if (choice && choice.outcome === "accepted") {
                localStorage.setItem("pp_pwa_installed", "true");
                hideInstallButton();
                showToast("PressureProof installed successfully!");
            } else {
                showToast("Install prompt was dismissed. Try the button again.");
            }
            deferredPrompt = null;
            return;
        }

        if (isIos) {
            openIosModal();
            return;
        }

        await openDiagnosticsModal();
        const diagnostics = lastInstallDiagnostics || {};
        const missing = [];
        if (!diagnostics.isSecureContext) {
            missing.push("secure context");
        }
        if (!diagnostics.supportsServiceWorker) {
            missing.push("service worker support");
        }
        if (!diagnostics.hasController) {
            missing.push("active service worker control");
        }
        if (!diagnostics.manifestOk) {
            missing.push("manifest fetch");
        }
        if (missing.length > 0) {
            showToast(`Install is blocked until ${missing.join(", ")} is fixed.`);
        } else {
            showToast("The app looks installable, but this browser has not fired beforeinstallprompt yet. Keep using the app and try again.");
        }
    }

    window.addEventListener("beforeinstallprompt", (event) => {
        event.preventDefault();
        deferredPrompt = event;
        showInstallButton();
        if (window.console && typeof window.console.info === "function") {
            window.console.info("[PressureProof] beforeinstallprompt fired");
        }
    });

    window.addEventListener("appinstalled", () => {
        localStorage.setItem("pp_pwa_installed", "true");
        hideInstallButton();
        showToast("PressureProof installed successfully!");
    });

    installButtons.forEach((button) => {
        button.addEventListener("click", async () => {
            try {
                await attemptInstall();
            } catch (error) {
                showToast("Install could not start right now. Please reload and try again.");
                if (window.console && typeof window.console.error === "function") {
                    window.console.error("[PressureProof] install failed", error);
                }
            }
        });
    });

    setStandaloneClasses();

    if (isStandalone || localStorage.getItem("pp_pwa_installed") === "true") {
        hideInstallButton();
    } else {
        showInstallButton();
    }

    if (window.console && typeof window.console.info === "function") {
        window.console.info("[PressureProof] install script ready", {
            isSecureContext: window.isSecureContext === true,
            supportsServiceWorker: "serviceWorker" in navigator,
            isStandalone: isStandalone,
            isIos: isIos,
            isAndroid: isAndroid,
        });
    }
})();
