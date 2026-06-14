(function () {
    const DB_NAME = "PressureProofDB";
    const DB_VERSION = 1;

    const STORES = {
        user_preferences: { keyPath: "key" },
        cached_lsrc_data: { keyPath: "week", indexes: [{ name: "user_id", keyPath: "user_id" }] },
        cached_pgi_trend: { keyPath: "user_id" },
        cached_dashboard: { keyPath: "user_id" },
        pending_syncs: { keyPath: "id", autoIncrement: true, indexes: [{ name: "type", keyPath: "type" }] },
        offline_sessions: { keyPath: "session_id" },
    };

    let dbPromise = null;

    function openDb() {
        if (dbPromise) {
            return dbPromise;
        }

        dbPromise = new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);

            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                Object.entries(STORES).forEach(([name, config]) => {
                    if (!db.objectStoreNames.contains(name)) {
                        const store = db.createObjectStore(name, {
                            keyPath: config.keyPath,
                            autoIncrement: config.autoIncrement || false,
                        });
                        (config.indexes || []).forEach((index) => {
                            store.createIndex(index.name, index.keyPath, { unique: false });
                        });
                    }
                });
            };

            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });

        return dbPromise;
    }

    function withStore(storeName, mode, operation) {
        return openDb().then((db) => new Promise((resolve, reject) => {
            const transaction = db.transaction(storeName, mode);
            const store = transaction.objectStore(storeName);
            const request = operation(store);

            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        }));
    }

    function get(storeName, key) {
        return withStore(storeName, "readonly", (store) => store.get(key));
    }

    function set(storeName, value) {
        return withStore(storeName, "readwrite", (store) => store.put(value));
    }

    function remove(storeName, key) {
        return withStore(storeName, "readwrite", (store) => store.delete(key));
    }

    function getAll(storeName) {
        return withStore(storeName, "readonly", (store) => store.getAll());
    }

    function addPendingSync(type, url, method, body, headers) {
        const payload = {
            type,
            url,
            method: method || "POST",
            body: body || null,
            headers: headers || {},
            created_at: Date.now(),
            retry_count: 0,
            next_attempt_at: 0,
        };
        return withStore("pending_syncs", "readwrite", (store) => store.add(payload));
    }

    async function getPendingSync() {
        const items = await getAll("pending_syncs");
        return (items || []).sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
    }

    function removePendingSync(id) {
        return remove("pending_syncs", id);
    }

    const PPDB = {
        init: openDb,
        get,
        set,
        delete: remove,
        getAll,
        addPendingSync,
        getPendingSync,
        removePendingSync,
    };

    window.PPDB = PPDB;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
            PPDB.init().catch(() => null);
        });
    } else {
        PPDB.init().catch(() => null);
    }
})();
