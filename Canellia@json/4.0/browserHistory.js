const GLib = imports.gi.GLib;
const Util = imports.misc.util;
const {getChromiumProfileDirs} = require('./utils');
const {runJsonScript} = require('./process');

async function searchBrowserProfile(applet, currentSearchId, path, appInfo, pattern) {
    if (currentSearchId !== applet.currentSearchId || applet.willUnmount) return [];
    const fullPath = GLib.build_filenamev([GLib.get_user_config_dir()].concat(path));
    if (!GLib.file_test(fullPath + '/History', GLib.FileTest.EXISTS)) return [];
    const results = await runJsonScript('searchHistory.py', [fullPath, pattern], []);
    if (currentSearchId !== applet.currentSearchId || applet.willUnmount) return [];
    return results.filter(result => result && typeof result.uri === 'string' &&
        typeof result.name === 'string').map(result => {
        result.app = appInfo;
        if (!result.icon_filename) result.gicon = appInfo.get_icon();
        result.isSearchResult = true;
        result.deleteAfterUse = true;
        result.activate = () => Util.spawn(['xdg-open', result.uri]);
        return result;
    });
}

function searchBrowserHistory(applet, currentSearchId, pattern, callback) {
    if (currentSearchId !== applet.currentSearchId || applet.willUnmount) return;
    Promise.resolve().then(() => Promise.all(getChromiumProfileDirs().map(profile =>
        searchBrowserProfile(applet, currentSearchId, profile[0], profile[1], pattern)
            .catch(error => {
                global.logWarning(`Canellia: ${error.message}`);
                return [];
            })
    ))).then(results => {
        if (currentSearchId !== applet.currentSearchId || applet.willUnmount) return;
        const unique = new Map();
        results.forEach(profile => profile.forEach(result => {
            if (!unique.has(result.uri)) unique.set(result.uri, result);
        }));
        callback(Array.from(unique.values()).slice(0, 20));
    }).catch(error => {
        global.logWarning(`Canellia: ${error.message}`);
        if (currentSearchId === applet.currentSearchId && !applet.willUnmount) callback([]);
    });
}

module.exports = {searchBrowserHistory};
