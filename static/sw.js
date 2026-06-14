const CACHE_VERSION = "CACHE_VERSION";
const STATIC_CACHE_NAME = `pp-static-v${CACHE_VERSION}`;
const DYNAMIC_CACHE_NAME = `pp-dynamic-v${CACHE_VERSION}`;
const AUDIO_CACHE_NAME = `pp-audio-v${CACHE_VERSION}`;
const OFFLINE_PAGE_URL = "/offline";

const STATIC_ASSETS = [
    "/",
    OFFLINE_PAGE_URL,
    "/manifest.json",
    "/static/css/main.css",
    "/static/css/components.css",
    "/static/css/dashboard.css",
    "/static/css/session.css",
    "/static/css/snapspeak.css",
    "/static/vendor/bootstrap/bootstrap.min.css",
    "/static/vendor/bootstrap/bootstrap.bundle.min.js",
    "/static/vendor/chartjs/chart.min.js",
    "/static/js/audio_recorder.js",
    "/static/js/lsrc_chart.js",
    "/static/js/onboarding_step2.js",
    "/static/js/pgi_chart.js",
    "/static/js/push_notifications.js",
    "/static/js/session_controller.js",
    "/static/js/waveform.js",
    "/static/js/pp_db.js",
    "/static/js/connectivity.js",
    "/static/js/sw_register.js",
    "/static/js/pwa_install.js",
    "/static/img/logo.svg",
    "/static/img/pressureproof-icon.svg",
    "/static/img/avatars/avatar_impatient.svg",
    "/static/img/avatars/avatar_neutral.svg",
    "/static/img/icons/icon.svg",
    "/static/img/icons/icon-48.png",
    "/static/img/icons/icon-72.png",
    "/static/img/icons/icon-96.png",
    "/static/img/icons/icon-120.png",
    "/static/img/icons/icon-128.png",
    "/static/img/icons/icon-144.png",
    "/static/img/icons/icon-152.png",
    "/static/img/icons/icon-167.png",
    "/static/img/icons/icon-180.png",
    "/static/img/icons/icon-192.png",
    "/static/img/icons/icon-256.png",
    "/static/img/icons/icon-384.png",
    "/static/img/icons/icon-512.png",
    "/static/fonts/Inter-Regular.woff2",
    "/static/fonts/Inter-Medium.woff2",
    "/static/fonts/Inter-SemiBold.woff2",
    "/static/fonts/Inter-Bold.woff2",
];

const AUDIO_MAX_ENTRIES = 20;
const API_CACHE_TTL_MS = 24 * 60 * 60 * 1000;

const DB_NAME = "PressureProofDB";
const DB_VERSION = 1;
const PENDING_STORE = "pending_syncs";

function isHttpRequest(url) {
    return url.startsWith("http://") || url.startsWith("https://");
}

function isExternalRequest(url) {
    return url.origin !== self.location.origin;
}

function isRazorpayRequest(url) {
    return url.hostname === "checkout.razorpay.com";
}

function isApiRequest(url) {
    return url.origin === self.location.origin && url.pathname.startsWith("/api/");
}

function isAudioRequest(request, url) {
    if (request.destination === "audio") {
        return true;
    }
    return url.origin === self.location.origin && url.pathname.startsWith("/static/audio/");
}

function isStaticAsset(request, url) {
    const destination = request.destination;
    if (["style", "script", "image", "font"].includes(destination)) {
        return true;
    }

    if (url.origin !== self.location.origin) {
        return false;
    }

    return /\.(css|js|png|jpg|jpeg|svg|webp|gif|woff2|woff|ttf|eot|ico)$/i.test(url.pathname);
}

function createTimeoutPromise(timeoutMs) {
    return new Promise((_, reject) => {
        setTimeout(() => reject(new Error("timeout")), timeoutMs);
    });
}

async function fetchWithTimeout(request, timeoutMs) {
    return Promise.race([fetch(request), createTimeoutPromise(timeoutMs)]);
}

async function cachePut(cacheName, request, response) {
    if (!response || response.status !== 200) {
        return;
    }
    const cache = await caches.open(cacheName);
    await cache.put(request, response);
}

async function limitCacheEntries(cacheName, maxEntries) {
    const cache = await caches.open(cacheName);
    const keys = await cache.keys();
    if (keys.length <= maxEntries) {
        return;
    }
    const extra = keys.length - maxEntries;
    for (let index = 0; index < extra; index += 1) {
        await cache.delete(keys[index]);
    }
}

function cloneResponseWithHeaders(response, extraHeaders) {
    const headers = new Headers(response.headers);
    Object.entries(extraHeaders || {}).forEach(([key, value]) => {
        headers.set(key, value);
    });
    return response.clone().blob().then((body) => new Response(body, {
        status: response.status,
        statusText: response.statusText,
        headers,
    }));
}

function openDb() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains(PENDING_STORE)) {
                const store = db.createObjectStore(PENDING_STORE, { keyPath: "id", autoIncrement: true });
                store.createIndex("type", "type", { unique: false });
            }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

async function getPendingSyncs() {
    const db = await openDb();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(PENDING_STORE, "readonly");
        const store = tx.objectStore(PENDING_STORE);
        const req = store.getAll();
        req.onsuccess = () => resolve(req.result || []);
        req.onerror = () => reject(req.error);
    });
}

async function updatePendingSync(item) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(PENDING_STORE, "readwrite");
        const store = tx.objectStore(PENDING_STORE);
        const req = store.put(item);
        req.onsuccess = () => resolve(true);
        req.onerror = () => reject(req.error);
    });
}

async function removePendingSync(id) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(PENDING_STORE, "readwrite");
        const store = tx.objectStore(PENDING_STORE);
        const req = store.delete(id);
        req.onsuccess = () => resolve(true);
        req.onerror = () => reject(req.error);
    });
}

function shouldAttempt(item) {
    if (!item) {
        return false;
    }
    const nextAttempt = Number(item.next_attempt_at || 0);
    if (!nextAttempt) {
        return true;
    }
    return Date.now() >= nextAttempt;
}

function computeNextAttempt(retryCount) {
    const baseDelay = 60 * 1000;
    const maxDelay = 24 * 60 * 60 * 1000;
    const delay = Math.min(maxDelay, baseDelay * Math.pow(2, retryCount));
    return Date.now() + delay;
}

function base64ToBlob(base64, mimeType) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i);
    }
    return new Blob([bytes], { type: mimeType || "application/octet-stream" });
}

async function replayPendingSync(item) {
    if (!item || !item.url) {
        return false;
    }

    if (item.type === "audio_chunk" && (item.payload || item.body)) {
        const payload = item.payload || item.body;
        const formData = new FormData();
        const chunkBlob = base64ToBlob(payload.chunk_base64, payload.mime_type);
        formData.append("chunk", chunkBlob, payload.filename || "chunk.webm");
        formData.append("chunk_index", String(payload.chunk_index));
        if (payload.csrf_token) {
            formData.append("csrf_token", payload.csrf_token);
        }

        const headers = payload.headers || {};
        const response = await fetch(item.url, {
            method: "POST",
            credentials: "same-origin",
            headers,
            body: formData,
        });
        return response.ok;
    }

    const options = {
        method: item.method || "POST",
        credentials: "same-origin",
        headers: item.headers || {},
    };
    if (item.body) {
        options.body = item.body;
    }

    const response = await fetch(item.url, options);
    return response.ok;
}

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(STATIC_CACHE_NAME)
            .then((cache) => cache.addAll(STATIC_ASSETS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) => Promise.all(
            keys.map((key) => {
                if (!key.startsWith("pp-")) {
                    return null;
                }
                if ([STATIC_CACHE_NAME, DYNAMIC_CACHE_NAME, AUDIO_CACHE_NAME].includes(key)) {
                    return null;
                }
                return caches.delete(key);
            })
        )).then(() => self.clients.claim())
    );
});

self.addEventListener("message", (event) => {
    if (event.data && event.data.type === "SKIP_WAITING") {
        self.skipWaiting();
    }
});

self.addEventListener("sync", (event) => {
    if (event.tag !== "pp-background-sync") {
        return;
    }

    event.waitUntil((async () => {
        const items = await getPendingSyncs();
        for (const item of items) {
            if (!shouldAttempt(item)) {
                continue;
            }
            try {
                const ok = await replayPendingSync(item);
                if (ok) {
                    await removePendingSync(item.id);
                } else {
                    const retryCount = Number(item.retry_count || 0) + 1;
                    item.retry_count = retryCount;
                    item.next_attempt_at = computeNextAttempt(retryCount);
                    await updatePendingSync(item);
                }
            } catch (error) {
                const retryCount = Number(item.retry_count || 0) + 1;
                item.retry_count = retryCount;
                item.next_attempt_at = computeNextAttempt(retryCount);
                await updatePendingSync(item);
            }
        }
    })());
});

self.addEventListener("push", (event) => {
    let payload = {};
    if (event.data) {
        try {
            payload = event.data.json();
        } catch (error) {
            payload = {};
        }
    }

    const title = payload.title || "PressureProof";
    const options = {
        body: payload.body || "You have a new update from PressureProof.",
        icon: "/static/img/icons/icon-192.png",
        badge: "/static/img/icons/icon-72.png",
        data: {
            url: payload.url || "/dashboard",
        },
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const targetUrl = (event.notification.data && event.notification.data.url) || "/dashboard";
    event.waitUntil(self.clients.openWindow(targetUrl));
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    const url = new URL(request.url);

    if (!isHttpRequest(request.url)) {
        return;
    }

    if (isRazorpayRequest(url)) {
        event.respondWith(fetch(request));
        return;
    }

    if (isExternalRequest(url)) {
        event.respondWith((async () => {
            try {
                const response = await fetchWithTimeout(request, 8000);
                await cachePut(DYNAMIC_CACHE_NAME, request, response.clone());
                return response;
            } catch (error) {
                const cached = await caches.match(request);
                if (cached) {
                    return cached;
                }
                return new Response(JSON.stringify({ message: "Service temporarily unavailable. Please try again soon." }), {
                    status: 503,
                    headers: { "Content-Type": "application/json" },
                });
            }
        })());
        return;
    }

    if (request.mode === "navigate") {
        event.respondWith((async () => {
            try {
                const response = await fetch(request);
                if (response && response.ok) {
                    await cachePut(DYNAMIC_CACHE_NAME, request, response.clone());
                }
                return response;
            } catch (error) {
                const cached = await caches.match(request);
                if (cached) {
                    return cached;
                }
                const offlineCache = await caches.open(STATIC_CACHE_NAME);
                return offlineCache.match(OFFLINE_PAGE_URL);
            }
        })());
        return;
    }

    if (isAudioRequest(request, url)) {
        event.respondWith((async () => {
            const cache = await caches.open(AUDIO_CACHE_NAME);
            const cached = await cache.match(request);
            if (cached) {
                return cached;
            }
            try {
                const response = await fetch(request);
                if (response && response.ok) {
                    await cache.put(request, response.clone());
                    await limitCacheEntries(AUDIO_CACHE_NAME, AUDIO_MAX_ENTRIES);
                }
                return response;
            } catch (error) {
                return cached || new Response("", { status: 504 });
            }
        })());
        return;
    }

    if (isApiRequest(url)) {
        event.respondWith((async () => {
            if (request.method !== "GET") {
                try {
                    return await fetch(request);
                } catch (error) {
                    return new Response(JSON.stringify({ offline: true, message: "No internet connection. Showing last available data." }), {
                        status: 503,
                        headers: { "Content-Type": "application/json" },
                    });
                }
            }

            try {
                const response = await fetchWithTimeout(request, 5000);
                if (response && response.ok) {
                    const stamped = await cloneResponseWithHeaders(response, {
                        "X-Cache-Timestamp": String(Date.now()),
                    });
                    await cachePut(DYNAMIC_CACHE_NAME, request, stamped.clone());
                    return response;
                }
                return response;
            } catch (error) {
                const cached = await caches.match(request);
                if (cached) {
                    const cacheTime = Number(cached.headers.get("X-Cache-Timestamp") || 0);
                    if (cacheTime && Date.now() - cacheTime <= API_CACHE_TTL_MS) {
                        return cloneResponseWithHeaders(cached, { "X-Served-From": "cache" });
                    }
                }
                return new Response(JSON.stringify({ offline: true, message: "No internet connection. Showing last available data." }), {
                    status: 503,
                    headers: { "Content-Type": "application/json" },
                });
            }
        })());
        return;
    }

    if (isStaticAsset(request, url)) {
        event.respondWith((async () => {
            const cache = await caches.open(STATIC_CACHE_NAME);
            const cached = await cache.match(request);
            if (cached) {
                return cached;
            }
            try {
                const response = await fetch(request);
                if (response && response.ok) {
                    await cache.put(request, response.clone());
                }
                return response;
            } catch (error) {
                return cached || new Response("", { status: 504 });
            }
        })());
        return;
    }

    event.respondWith((async () => {
        const cache = await caches.open(DYNAMIC_CACHE_NAME);
        const cached = await cache.match(request);
        const networkFetch = fetch(request)
            .then(async (response) => {
                if (response && response.ok) {
                    await cache.put(request, response.clone());
                }
                return response;
            })
            .catch(() => null);

        if (cached) {
            networkFetch.catch(() => null);
            return cached;
        }

        const response = await networkFetch;
        if (response) {
            return response;
        }

        if (request.mode === "navigate") {
            const offlineCache = await caches.open(STATIC_CACHE_NAME);
            return offlineCache.match(OFFLINE_PAGE_URL);
        }

        return new Response("", { status: 504 });
    })());
});
