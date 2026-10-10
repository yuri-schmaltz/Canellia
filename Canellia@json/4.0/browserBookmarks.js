/* ========================================================================================================
 *  CREDITS:  Code borrowed from SearchBookmarks extension by bmh1980
 *            at https://extensions.gnome.org/extension/557/search-bookmarks/
 * ========================================================================================================
 */
/**
 * Copyright (C) 2012 Marcus Habermehl <bmh1980de@gmail.com>
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version 2
 * of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
 * USA.
 */
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const ByteArray = imports.byteArray;
const Cinnamon = imports.gi.Cinnamon;
const Util = imports.misc.util;
const {getChromiumProfileDirs} = require('./utils');
const {runJsonScript} = require('./process');

const readFileAsync = function(file, opts = {utf8: true}) {
    const {utf8} = opts;
    return new Promise(function(resolve, reject) {
        if (typeof file === 'string' || file instanceof String) {
            file = Gio.File.new_for_path(file);
        }
        if (!file.query_exists(null)) return reject(new Error('File does not exist.'));
        file.load_contents_async(null, function(object, result) {
            try {
                let [success, data] = file.load_contents_finish(result);
                if (!success) return reject(new Error('File cannot be read.'));
                if (utf8) {
                    if (data instanceof Uint8Array) data = ByteArray.toString(data);
                    else data = data.toString();
                }
                resolve(data);
            } catch(e) {
                reject(e);
            }
        });
    });
};

const readJSONAsync = function(file) {
    return readFileAsync(file).then(function(json) {
        return JSON.parse(json);
    });
};

async function readFirefoxProfiles(browser) {
    const app = Cinnamon.AppSystem.get_default().lookup_desktop_wmclass(browser);
    if (!app) return [];
    const appInfo = app.get_app_info();
    if (!appInfo) return [];
    const bookmarks = await runJsonScript('firefoxBookmarks.py', [browser], []);
    return bookmarks.filter(bookmark => bookmark && typeof bookmark.name === 'string' &&
        typeof bookmark.uri === 'string' && /^https?:\/\//i.test(bookmark.uri))
        .map(bookmark => Object.assign({}, bookmark, {app: appInfo}));
}

const readChromiumBookmarksFile = async function(path, appInfo) {
    try {
        const bookmarksFile = Gio.File.new_for_path(GLib.build_filenamev(
            [GLib.get_user_config_dir(), ...path, 'Bookmarks']));
        if (!bookmarksFile.query_exists(null)) return [];
        const data = await readJSONAsync(bookmarksFile);
        if (!data || !data.roots || typeof data.roots !== 'object') return [];
        const foundBookmarks = [];
        const pending = Object.values(data.roots);
        while (pending.length) {
            const child = pending.pop();
            if (!child || typeof child !== 'object') continue;
            if (Array.isArray(child.children)) {
                for (const nested of child.children) pending.push(nested);
            }
            if (child.type !== 'url' || typeof child.url !== 'string' ||
                typeof child.name !== 'string') continue;
            const match = /^(https?:\/\/[^/?#]+)(?:[/?#]|$)/i.exec(child.url);
            if (!match) continue;
            foundBookmarks.push({app: appInfo, name: child.name,
                uri: child.url, domain: match[1]});
        }
        if (!foundBookmarks.length) return [];
        const faviconsFile = GLib.build_filenamev([GLib.get_user_config_dir(), ...path, 'Favicons']);
        const domains = Array.from(new Set(foundBookmarks.map(bookmark => bookmark.domain)));
        const icons = await runJsonScript('getFavicons.py', [faviconsFile, JSON.stringify(domains)], {});
        foundBookmarks.forEach(bookmark => {
            if (typeof icons[bookmark.domain] === 'string') bookmark.icon_filename = icons[bookmark.domain];
        });
        return foundBookmarks;
    } catch (error) {
        global.logWarning(`Canellia: Unable to read browser bookmarks: ${error.message}`);
        return [];
    }
};

//=====================

let bookmarks = null;
let bookmarksTime = 0;
let pendingBookmarks = null;
const BOOKMARKS_CACHE_MS = 30000;

const getWebBookmarksAsync = function() {
    if (bookmarks && Date.now() - bookmarksTime < BOOKMARKS_CACHE_MS) {
        return Promise.resolve(bookmarks.map(bookmark => Object.assign({}, bookmark)));
    }
    if (pendingBookmarks) return pendingBookmarks.then(results => results.map(bookmark => Object.assign({}, bookmark)));
    pendingBookmarks = Promise.resolve().then(() => Promise.all([
        ...getChromiumProfileDirs().map(profile => readChromiumBookmarksFile(profile[0], profile[1])),
        ...['firefox', 'librewolf'].map(browser => readFirefoxProfiles(browser).catch(error => {
            global.logWarning(`Canellia: Unable to read ${browser} bookmarks: ${error.message}`);
            return [];
        }))
    ])).then(results => {
        const found = [].concat(...results);
        const unique = new Map();
        found.forEach(bookmark => {
            if (!bookmark || typeof bookmark.name !== 'string' || typeof bookmark.uri !== 'string') return;
            if (!bookmark.icon_filename) bookmark.gicon = bookmark.app.get_icon();
            bookmark.description = bookmark.uri.length > 150 ? bookmark.uri.slice(0, 150) + ' ...' : bookmark.uri;
            bookmark.isSearchResult = true;
            bookmark.activate = () => Util.spawn(['xdg-open', bookmark.uri]);
            unique.set(bookmark.uri, bookmark);
        });
        bookmarks = Array.from(unique.values()).sort((a, b) => a.name.localeCompare(b.name));
        bookmarksTime = Date.now();
        return bookmarks;
    }).catch(error => {
        global.logWarning(`Canellia: ${error.message}`);
        return [];
    }).then(results => {
        pendingBookmarks = null;
        return results;
    });
    // Each search assigns scores, so cached bookmark objects must not be shared.
    return pendingBookmarks.then(results => results.map(bookmark => Object.assign({}, bookmark)));
};

module.exports = {getWebBookmarksAsync};
