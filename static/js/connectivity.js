(function () {
    const banner = document.getElementById("connectivityBanner");
    if (!banner) {
        return;
    }

    const textEl = banner.querySelector(".pp-connectivity-text");

    function dispatchConnectivityEvent(isOnline) {
        document.dispatchEvent(new CustomEvent("pp:connectivity", { detail: { online: isOnline } }));
    }

    function showBanner() {
        banner.classList.add("is-visible");
    }

    function hideBanner() {
        banner.classList.remove("is-visible");
    }

    function setOfflineState() {
        banner.classList.remove("is-online");
        banner.classList.add("is-offline");
        if (textEl) {
            textEl.textContent = "You are offline. Showing saved content.";
        }
        showBanner();
        dispatchConnectivityEvent(false);
    }

    function setOnlineState() {
        banner.classList.remove("is-offline");
        banner.classList.add("is-online");
        if (textEl) {
            textEl.textContent = "Back online. Syncing now.";
        }
        showBanner();
        dispatchConnectivityEvent(true);

        if ("serviceWorker" in navigator) {
            navigator.serviceWorker.ready
                .then((registration) => {
                    if (registration && "sync" in registration) {
                        return registration.sync.register("pp-background-sync");
                    }
                    return null;
                })
                .catch(() => null);
        }

        window.setTimeout(() => {
            hideBanner();
        }, 2000);
    }

    window.addEventListener("offline", setOfflineState);
    window.addEventListener("online", setOnlineState);

    if (!navigator.onLine) {
        setOfflineState();
    } else {
        dispatchConnectivityEvent(true);
    }
})();
