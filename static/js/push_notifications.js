function getCsrfToken() {
    const tokenElement = document.querySelector('meta[name="csrf-token"]');
    if (tokenElement && tokenElement.content) {
        return tokenElement.content;
    }
    return "";
}

function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = atob(base64);
    const outputArray = new Uint8Array(rawData.length);

    for (let index = 0; index < rawData.length; index += 1) {
        outputArray[index] = rawData.charCodeAt(index);
    }

    return outputArray;
}

async function sendSubscriptionToServer(subscription) {
    const response = await fetch("/api/push/subscribe", {
        method: "POST",
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify(subscription.toJSON()),
    });
    return response;
}

async function requestPushPermission(vapidPublicKey) {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        console.log("Push notifications not supported");
        return false;
    }

    if (!("Notification" in window)) {
        console.log("Notification API not supported");
        return false;
    }

    if (!vapidPublicKey) {
        console.warn("VAPID public key is missing. Push notifications disabled.");
        return false;
    }

        let registration = await navigator.serviceWorker.getRegistration();
        if (!registration) {
                registration = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
        }

    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
        return false;
    }

    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
        subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
        });
    }

    const response = await sendSubscriptionToServer(subscription);
    return response.ok;
}

async function unsubscribeFromPush() {
    if (!("serviceWorker" in navigator)) {
        return false;
    }

    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
        return true;
    }

    const endpoint = subscription.endpoint;
    await subscription.unsubscribe();

    const response = await fetch("/api/push/unsubscribe", {
        method: "POST",
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({ endpoint }),
    });
    return response.ok;
}

window.PushNotifications = {
    requestPushPermission,
    unsubscribeFromPush,
    sendSubscriptionToServer,
};
