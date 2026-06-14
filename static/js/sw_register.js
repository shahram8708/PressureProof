(function () {
    const body = document.body;
    if (body && body.dataset && body.dataset.noSwCheck === "true") {
        return;
    }

    if (!("serviceWorker" in navigator)) {
        return;
    }

    const envMeta = document.querySelector('meta[name="flask-env"]');
    const env = envMeta ? envMeta.content : "";
    const isDev = env === "development";
    const bootstrapReloadKey = "pp_sw_bootstrap_reload_done";

    let refreshing = false;

    function log(message, data) {
        if (!isDev) {
            return;
        }
        if (data !== undefined) {
            console.log(message, data);
        } else {
            console.log(message);
        }
    }

    function showUpdateToast(registration) {
        const existing = document.getElementById("ppSwUpdateToast");
        if (existing) {
            return;
        }

        const container = document.createElement("div");
        container.className = "toast-container position-fixed bottom-0 end-0 p-3";
        container.style.zIndex = "2000";

        const toastEl = document.createElement("div");
        toastEl.id = "ppSwUpdateToast";
        toastEl.className = "toast align-items-center text-bg-dark border-0";
        toastEl.setAttribute("role", "status");
        toastEl.setAttribute("aria-live", "polite");
        toastEl.setAttribute("aria-atomic", "true");

        toastEl.innerHTML = "" +
            "<div class=\"d-flex\">" +
            "<div class=\"toast-body\">A new version of PressureProof is available.</div>" +
            "<button type=\"button\" class=\"btn btn-warning btn-sm ms-2 me-2\" id=\"ppSwUpdateBtn\">Update now</button>" +
            "<button type=\"button\" class=\"btn-close btn-close-white me-2 m-auto\" data-bs-dismiss=\"toast\" aria-label=\"Close\"></button>" +
            "</div>";

        container.appendChild(toastEl);
        document.body.appendChild(container);

        const updateBtn = toastEl.querySelector("#ppSwUpdateBtn");
        if (updateBtn) {
            updateBtn.addEventListener("click", () => {
                if (registration && registration.waiting) {
                    registration.waiting.postMessage({ type: "SKIP_WAITING" });
                }
            });
        }

        if (window.bootstrap && window.bootstrap.Toast) {
            const toast = new window.bootstrap.Toast(toastEl, { autohide: false });
            toast.show();
        } else {
            toastEl.classList.add("show");
        }
    }

    navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (refreshing) {
            return;
        }
        refreshing = true;
        window.location.reload();
    });

    navigator.serviceWorker.register("/sw.js", { scope: "/" })
        .then((registration) => {
            log("Service worker registered", registration);

            navigator.serviceWorker.ready
                .then(() => {
                    if (navigator.serviceWorker.controller) {
                        sessionStorage.removeItem(bootstrapReloadKey);
                        return;
                    }

                    if (sessionStorage.getItem(bootstrapReloadKey) === "true") {
                        return;
                    }

                    sessionStorage.setItem(bootstrapReloadKey, "true");
                    window.location.reload();
                })
                .catch((error) => {
                    log("Service worker readiness check failed", error);
                });

            if (registration.waiting) {
                showUpdateToast(registration);
            }

            registration.addEventListener("updatefound", () => {
                const newWorker = registration.installing;
                log("Service worker update found");
                if (!newWorker) {
                    return;
                }
                newWorker.addEventListener("statechange", () => {
                    log("Service worker state", newWorker.state);
                    if (newWorker.state === "installed" && navigator.serviceWorker.controller) {
                        showUpdateToast(registration);
                    }
                });
            });
        })
        .catch((error) => {
            log("Service worker registration failed", error);
        });
})();
