(function () {
    "use strict";

    const app = ACEUIAppLoader.app("ace-standings-bridge");

    function publish() {
        const models = window.ksUI && window.ksUI.Models;
        if (models && models.Disabled && models.Disabled.indexOf("ModelLeaderboard") >= 0) {
            models.enable("ModelLeaderboard");
        }
        const leaderboard = window.ModelLeaderboard;
        const rows = Array.from(leaderboard && leaderboard.lines || [], function (row) {
            const name = [row.first_name, row.last_name].filter(Boolean).join(" ").replace(/^•\s*/, "");
            return [row.pos, name, row.car_name || "", row.focused === true,
                row.time_diff || "", row.best_lap_time || "", row.last_lap_time || ""];
        });
        app.log("ACE_OVERLAY_GRID_V1 " + JSON.stringify([Date.now(), rows]));
    }

    app.mount(function () {
        publish();
        return window.setInterval(publish, 1000);
    }, function (timer) {
        window.clearInterval(timer);
        app.log("ACE_OVERLAY_GRID_V1 " + JSON.stringify([Date.now(), []]));
    });
}());
