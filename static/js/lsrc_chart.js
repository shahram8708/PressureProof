let lsrcRadarInstance = null;

function getUserId() {
    const meta = document.querySelector('meta[name="user-id"]');
    if (!meta || !meta.content) {
        return null;
    }
    return meta.content;
}

function ensureCacheNotice(canvas) {
    const existing = document.getElementById("lsrcCacheNotice");
    if (existing) {
        return existing;
    }

    const notice = document.createElement("div");
    notice.id = "lsrcCacheNotice";
    notice.className = "small text-secondary mt-2";

    const container = canvas.closest(".pp-chart-radar-container") || canvas.parentElement;
    if (container && container.parentElement) {
        container.parentElement.appendChild(notice);
    }
    return notice;
}

function updateCacheNotice(canvas, timestamp) {
    if (!canvas) {
        return;
    }
    const notice = ensureCacheNotice(canvas);
    if (!timestamp) {
        notice.textContent = "";
        notice.style.display = "none";
        return;
    }
    const dateText = new Date(timestamp).toLocaleString();
    notice.textContent = `Cached data - last updated ${dateText}`;
    notice.style.display = "block";
}

function buildEmptyChartData(chartData) {
    const labels = Array.isArray(chartData.labels) ? chartData.labels : [];
    const emptyValues = labels.map(() => 0);
    return {
        labels,
        datasets: [
            {
                label: "Prepared English",
                data: emptyValues,
                borderColor: "#4F46E5",
                backgroundColor: "rgba(79,70,229,0.15)",
                pointBackgroundColor: "#4F46E5",
            },
            {
                label: "English Under Pressure",
                data: emptyValues,
                borderColor: "#F59E0B",
                backgroundColor: "rgba(245,158,11,0.15)",
                pointBackgroundColor: "#F59E0B",
            },
        ],
    };
}

function normalizeChartData(chartData) {
    if (!chartData || chartData.has_data === false) {
        return buildEmptyChartData(chartData || {});
    }

    const labels = Array.isArray(chartData.labels) ? chartData.labels : [];
    const datasets = Array.isArray(chartData.datasets) ? chartData.datasets : [];
    return {
        labels,
        datasets,
    };
}

function initLsrcChart(canvasId, chartData) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === "undefined") {
        return null;
    }

    if (lsrcRadarInstance) {
        lsrcRadarInstance.destroy();
        lsrcRadarInstance = null;
    }

    const wrapper = canvas.parentElement;
    if (wrapper) {
        if (chartData && chartData.has_data === false) {
            wrapper.classList.add("pp-chart-empty");
        } else {
            wrapper.classList.remove("pp-chart-empty");
        }
    }

    const normalizedData = normalizeChartData(chartData || {});

    lsrcRadarInstance = new Chart(canvas, {
        type: "radar",
        data: normalizedData,
        options: {
            responsive: true,
            maintainAspectRatio: true,
            animation: {
                duration: 600,
                easing: "easeInOutQuart",
            },
            scales: {
                r: {
                    min: 0,
                    max: 100,
                    ticks: {
                        stepSize: 20,
                        color: "#6B7280",
                        backdropColor: "transparent",
                    },
                    pointLabels: {
                        color: "#111827",
                        font: {
                            family: "Inter",
                            size: 13,
                        },
                    },
                    grid: {
                        color: "#E5E7EB",
                    },
                    angleLines: {
                        color: "#E5E7EB",
                    },
                },
            },
            plugins: {
                legend: {
                    position: "bottom",
                    labels: {
                        usePointStyle: true,
                        color: "#111827",
                        font: {
                            family: "Inter",
                            size: 13,
                        },
                    },
                },
            },
        },
    });

    return lsrcRadarInstance;
}

async function updateLsrcChart(week) {
    const canvas = document.getElementById("lsrcRadarChart");
    const userId = getUserId();

    if (!navigator.onLine && window.PPDB) {
        try {
            const cached = await window.PPDB.get("cached_lsrc_data", week);
            if (cached && cached.data) {
                updateCacheNotice(canvas, cached.cached_at);
                return initLsrcChart("lsrcRadarChart", cached.data);
            }
        } catch (error) {
            updateCacheNotice(canvas, null);
        }
    }

    try {
        const response = await fetch(`/api/lsrc/${encodeURIComponent(week)}`, {
            credentials: "same-origin",
        });
        if (!response.ok) {
            return null;
        }

        const chartData = await response.json();
        updateCacheNotice(canvas, null);
        if (window.PPDB && userId) {
            await window.PPDB.set("cached_lsrc_data", {
                week,
                user_id: userId,
                data: chartData,
                cached_at: new Date().toISOString(),
            });
        }
        if (lsrcRadarInstance) {
            lsrcRadarInstance.destroy();
            lsrcRadarInstance = null;
        }
        return initLsrcChart("lsrcRadarChart", chartData);
    } catch (error) {
        if (window.PPDB) {
            try {
                const cached = await window.PPDB.get("cached_lsrc_data", week);
                if (cached && cached.data) {
                    updateCacheNotice(canvas, cached.cached_at);
                    return initLsrcChart("lsrcRadarChart", cached.data);
                }
            } catch (readError) {
                updateCacheNotice(canvas, null);
            }
        }
        return null;
    }
}

window.initLsrcChart = initLsrcChart;
window.updateLsrcChart = updateLsrcChart;
