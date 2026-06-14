let pgiTrendInstance = null;
let sparklineInstances = {};
let contributionInstance = null;

function getUserId() {
    const meta = document.querySelector('meta[name="user-id"]');
    if (!meta || !meta.content) {
        return null;
    }
    return meta.content;
}

function ensurePgiCacheNotice(canvas) {
    const existing = document.getElementById("pgiCacheNotice");
    if (existing) {
        return existing;
    }

    const notice = document.createElement("div");
    notice.id = "pgiCacheNotice";
    notice.className = "small text-secondary mt-2";

    const container = canvas ? canvas.parentElement : null;
    if (container && container.parentElement) {
        container.parentElement.appendChild(notice);
    }
    return notice;
}

function updatePgiCacheNotice(canvas, timestamp) {
    if (!canvas) {
        return;
    }
    const notice = ensurePgiCacheNotice(canvas);
    if (!timestamp) {
        notice.textContent = "";
        notice.style.display = "none";
        return;
    }
    const dateText = new Date(timestamp).toLocaleString();
    notice.textContent = `Cached data - last updated ${dateText}`;
    notice.style.display = "block";
}

function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
}

function nextWeekLabelFromIso(isoDateString, offsetWeeks) {
    if (!isoDateString) {
        return `W+${offsetWeeks}`;
    }

    const baseDate = new Date(`${isoDateString}T00:00:00`);
    if (Number.isNaN(baseDate.getTime())) {
        return `W+${offsetWeeks}`;
    }

    const futureDate = new Date(baseDate);
    futureDate.setDate(baseDate.getDate() + (offsetWeeks * 7));
    const month = futureDate.toLocaleString("en-US", { month: "short" });
    const weekInMonth = Math.floor((futureDate.getDate() - 1) / 7) + 1;
    return `${month} W${weekInMonth}`;
}

function buildProjectionSeries(trendData, projectionData) {
    const labels = (trendData || []).map((row) => row.week_label);
    const historicalValues = (trendData || []).map((row) => {
        if (row.pgi_score === null || row.pgi_score === undefined) {
            return null;
        }
        return Number(row.pgi_score);
    });

    const slope = Number(projectionData.slope || 0);
    let lastKnownIndex = -1;
    let lastKnownValue = null;
    let lastKnownWeekStart = null;

    trendData.forEach((row, index) => {
        if (row.pgi_score !== null && row.pgi_score !== undefined) {
            lastKnownIndex = index;
            lastKnownValue = Number(row.pgi_score);
            lastKnownWeekStart = row.week_start;
        }
    });

    const futureLabels = [];
    for (let step = 1; step <= 4; step += 1) {
        futureLabels.push(nextWeekLabelFromIso(lastKnownWeekStart, step));
    }

    const combinedLabels = labels.concat(futureLabels);
    const historicalSeries = historicalValues.concat([null, null, null, null]);

    const projectedSeries = Array(combinedLabels.length).fill(null);
    if (lastKnownIndex >= 0 && lastKnownValue !== null) {
        let currentProjection = lastKnownValue;
        for (let index = lastKnownIndex; index < combinedLabels.length; index += 1) {
            if (index === lastKnownIndex) {
                projectedSeries[index] = Number(currentProjection.toFixed(2));
                continue;
            }
            currentProjection = clamp(currentProjection + slope, 0, 100);
            projectedSeries[index] = Number(currentProjection.toFixed(2));
        }
    }

    return {
        labels: combinedLabels,
        historicalSeries,
        projectedSeries,
    };
}

function initPgiChart(canvasId, trendData, projectionData) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === "undefined") {
        return null;
    }

    if (pgiTrendInstance) {
        pgiTrendInstance.destroy();
        pgiTrendInstance = null;
    }

    const projectionAvailable = Boolean(projectionData && projectionData.projection_available);
    const series = buildProjectionSeries(trendData || [], projectionData || {});

    const datasets = [
        {
            label: "Historical PGI",
            data: series.historicalSeries,
            borderColor: "#F59E0B",
            backgroundColor: "#F59E0B",
            borderWidth: 2.5,
            pointRadius: 4,
            pointBackgroundColor: "#F59E0B",
            tension: 0.3,
            fill: false,
            spanGaps: false,
        },
    ];

    if (projectionAvailable) {
        datasets.push({
            label: "Projected PGI",
            data: series.projectedSeries,
            borderColor: "#4F46E5",
            borderWidth: 1.5,
            borderDash: [6, 4],
            pointRadius: 0,
            tension: 0,
            fill: false,
            spanGaps: false,
        });
    }

    pgiTrendInstance = new Chart(canvas, {
        type: "line",
        data: {
            labels: series.labels,
            datasets,
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 500,
            },
            interaction: {
                mode: "index",
                intersect: false,
            },
            onHover(event) {
                const target = event?.native?.target;
                if (target && target.style) {
                    target.style.cursor = "crosshair";
                }
            },
            scales: {
                x: {
                    grid: {
                        color: "#E5E7EB",
                    },
                    ticks: {
                        color: "#111827",
                    },
                },
                y: {
                    min: 0,
                    max: 100,
                    title: {
                        display: true,
                        text: "PGI Score (Lower is better)",
                        color: "#111827",
                    },
                    grid: {
                        color: "#E5E7EB",
                    },
                    ticks: {
                        color: "#111827",
                    },
                },
            },
            plugins: {
                legend: {
                    display: projectionAvailable,
                    position: "bottom",
                },
                tooltip: {
                    callbacks: {
                        title(tooltipItems) {
                            if (!tooltipItems || tooltipItems.length === 0) {
                                return "";
                            }
                            return tooltipItems[0].label;
                        },
                        label(context) {
                            const value = context.parsed.y;
                            if (value === null || value === undefined) {
                                return "";
                            }
                            return `${context.dataset.label}: ${Number(value).toFixed(1)}. Lower is better.`;
                        },
                    },
                },
            },
        },
    });

    return pgiTrendInstance;
}

function initSparklineChart(canvasId, sparklineData) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === "undefined") {
        return null;
    }

    if (sparklineInstances[canvasId]) {
        sparklineInstances[canvasId].destroy();
    }

    const labels = (sparklineData || []).map((row) => row.week_label || "");
    const values = (sparklineData || []).map((row) => {
        if (row.pgi_score === null || row.pgi_score === undefined) {
            return null;
        }
        return Number(row.pgi_score);
    });

    sparklineInstances[canvasId] = new Chart(canvas, {
        type: "line",
        data: {
            labels,
            datasets: [
                {
                    data: values,
                    borderColor: "#F59E0B",
                    borderWidth: 2,
                    pointRadius: 2,
                    pointBackgroundColor: "#F59E0B",
                    fill: false,
                    tension: 0.3,
                    spanGaps: false,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 300,
            },
            plugins: {
                legend: {
                    display: false,
                },
                tooltip: {
                    enabled: false,
                },
            },
            scales: {
                x: {
                    display: false,
                    grid: {
                        display: false,
                    },
                },
                y: {
                    display: false,
                    min: 0,
                    max: 100,
                    grid: {
                        display: false,
                    },
                },
            },
        },
    });

    return sparklineInstances[canvasId];
}

function initDimensionContributionChart(canvasId, dimensionData) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === "undefined") {
        return null;
    }

    if (contributionInstance) {
        contributionInstance.destroy();
        contributionInstance = null;
    }

    const rows = [];
    const labels = Array.isArray(dimensionData?.labels) ? dimensionData.labels : [];
    const values = Array.isArray(dimensionData?.data) ? dimensionData.data : [];

    for (let index = 0; index < labels.length; index += 1) {
        rows.push({
            label: labels[index],
            value: Number(values[index] ?? 0),
        });
    }

    rows.sort((a, b) => b.value - a.value);

    contributionInstance = new Chart(canvas, {
        type: "bar",
        data: {
            labels: rows.map((row) => row.label),
            datasets: [
                {
                    data: rows.map((row) => row.value),
                    backgroundColor: "#F59E0B",
                    borderColor: "#F59E0B",
                    borderWidth: 1,
                },
            ],
        },
        options: {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false,
                },
            },
            scales: {
                x: {
                    min: 0,
                    max: 50,
                    title: {
                        display: true,
                        text: "Gap (points)",
                        color: "#111827",
                    },
                    grid: {
                        color: "#E5E7EB",
                    },
                    ticks: {
                        color: "#111827",
                    },
                },
                y: {
                    grid: {
                        display: false,
                    },
                    ticks: {
                        color: "#111827",
                    },
                },
            },
        },
    });

    return contributionInstance;
}

window.initPgiChart = initPgiChart;
window.initSparklineChart = initSparklineChart;
window.initDimensionContributionChart = initDimensionContributionChart;

window.loadPgiTrendChart = async function loadPgiTrendChart(canvasId, initialTrend, initialProjection) {
    const canvas = document.getElementById(canvasId);
    const userId = getUserId();

    if (!navigator.onLine && window.PPDB && userId) {
        try {
            const cached = await window.PPDB.get("cached_pgi_trend", userId);
            if (cached && cached.trend) {
                updatePgiCacheNotice(canvas, cached.cached_at);
                return initPgiChart(canvasId, cached.trend, cached.projection || {});
            }
        } catch (error) {
            updatePgiCacheNotice(canvas, null);
        }
    }

    if (navigator.onLine) {
        try {
            const response = await fetch("/api/pgi/trend?weeks=12", { credentials: "same-origin" });
            if (response.ok) {
                const payload = await response.json();
                const trend = payload.trend || [];
                const projection = payload.projection || {};
                updatePgiCacheNotice(canvas, null);
                if (window.PPDB && userId) {
                    await window.PPDB.set("cached_pgi_trend", {
                        user_id: userId,
                        trend,
                        projection,
                        cached_at: new Date().toISOString(),
                    });
                }
                return initPgiChart(canvasId, trend, projection);
            }
        } catch (error) {
            updatePgiCacheNotice(canvas, null);
        }
    }

    updatePgiCacheNotice(canvas, null);
    if (window.PPDB && userId && initialTrend) {
        try {
            await window.PPDB.set("cached_pgi_trend", {
                user_id: userId,
                trend: initialTrend,
                projection: initialProjection || {},
                cached_at: new Date().toISOString(),
            });
        } catch (error) {
            return initPgiChart(canvasId, initialTrend, initialProjection || {});
        }
    }
    return initPgiChart(canvasId, initialTrend, initialProjection || {});
};
