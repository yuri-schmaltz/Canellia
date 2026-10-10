const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const root = path.resolve(__dirname, '..');
const plain = value => JSON.parse(JSON.stringify(value));
function load(version, filename, imports, dependencies = {}, extra = '') {
    const context = vm.createContext({
        imports, module: {exports: {}}, require: name => dependencies[name] || {},
        global: {logWarning() {}, logError() {}, log() {}}, log() {},
        __meta: {path: '/applet/' + version}, setTimeout, clearTimeout,
    });
    vm.runInContext(fs.readFileSync(path.join(root, 'Canellia@json', version, filename), 'utf8') + extra, context);
    return context.module.exports;
}
function timers() {
    const active = new Map();
    let next = 1;
    return {
        active, PRIORITY_DEFAULT: 0, SOURCE_REMOVE: false,
        timeout_add(priority, delay, callback) {
            const id = next++;
            active.set(id, setTimeout(() => { active.delete(id); callback(); }, delay));
            return id;
        },
        source_remove(id) { clearTimeout(active.get(id)); active.delete(id); },
        build_filenamev: segments => segments.join('/'),
    };
}

for (const version of ['4.0', '5.8']) {
    test(`${version}: helper errors, malformed JSON and timeout always settle`, async () => {
        for (const scenario of ['valid', 'invalid-json', 'wrong-type', 'exit-error', 'launch-error', 'hung']) {
            const GLib = timers();
            let stopped = false;
            let argv;
            const Gio = {
                Cancellable: class { cancel() {} },
                SubprocessFlags: {STDOUT_PIPE: 1, STDERR_PIPE: 2},
                Subprocess: {new(args) {
                    argv = args;
                    if (scenario === 'launch-error') throw Error('missing Python');
                    return {
                        force_exit() { stopped = true; },
                        get_successful() { return scenario !== 'exit-error'; },
                        communicate_utf8_finish() {
                            return [true, scenario === 'invalid-json' ? 'bad' : scenario === 'wrong-type' ? '{}' : '[1,2]', 'diagnostic'];
                        },
                        communicate_utf8_async(stdin, cancellable, callback) {
                            if (scenario !== 'hung') setTimeout(() => callback(this, {}), 0);
                        },
                    };
                }},
            };
            const {runJsonScript} = load(version, 'process.js', {gi: {Gio, GLib}});
            const result = await runJsonScript('script.py', ['a b', '$(literal)'], [], scenario === 'hung' ? 5 : 100);
            assert.deepEqual(plain(result), scenario === 'valid' ? [1, 2] : []);
            assert.deepEqual(plain(argv), ['python3', '/applet/' + version + '/script.py', 'a b', '$(literal)']);
            assert.equal(GLib.active.size, 0);
            if (scenario === 'hung') assert.equal(stopped, true);
        }
    });

    test(`${version}: malformed bookmarks do not block healthy browser results`, async () => {
        let files = {
            '/config/broken/Bookmarks': '{invalid',
            '/config/healthy/Bookmarks': JSON.stringify({roots: {bar: {children: [
                {type: 'url', name: 'Home', url: 'https://example.com'},
                {type: 'url', name: 'Page', url: 'https://example.com/page'},
                {type: 'url', name: 'Bad', url: 'javascript:alert(1)'},
                {type: 'url', url: 'https://example.com/no-name'},
                null,
            ]}}}),
        };
        let reads = 0;
        const imports = {
            gi: {
                Gio: {File: {new_for_path(filename) {
                    return {
                        query_exists() { return Object.hasOwn(files, filename); },
                        load_contents_async(cancel, callback) { reads++; setTimeout(() => callback(this, {}), 0); },
                        load_contents_finish() { return [true, files[filename]]; },
                    };
                }}},
                GLib: {get_user_config_dir: () => '/config', build_filenamev: parts => parts.join('/')},
                Cinnamon: {AppSystem: {get_default: () => ({lookup_desktop_wmclass: () => null})}},
            },
            misc: {util: {spawn() {}}}, byteArray: {},
        };
        const app = {get_icon: () => 'browser'};
        const {getWebBookmarksAsync} = load(version, 'browserBookmarks.js', imports, {
            './utils': {getChromiumProfileDirs: () => [[['broken'], app], [['healthy'], app]]},
            './process': {runJsonScript: () => Promise.resolve({})},
        });
        const results = await Promise.race([
            getWebBookmarksAsync(), new Promise((resolve, reject) => {
                const timer = setTimeout(() => reject(Error('bookmarks never settled')), 100);
                timer.unref();
            }),
        ]);
        assert.deepEqual(plain(results.map(item => item.name)), ['Home', 'Page']);
        results[0].score = 999;
        const cached = await getWebBookmarksAsync();
        assert.equal(cached[0].score, undefined);
        assert.equal(reads, 2);
    });

    test(`${version}: history ignores obsolete searches and deduplicates profiles`, async () => {
        const completions = [];
        let calls = 0;
        const imports = {gi: {GLib: {get_user_config_dir: () => '/config',
            build_filenamev: parts => parts.join('/'), file_test: () => true, FileTest: {EXISTS: 1}}},
            misc: {util: {spawn() {}}}};
        const app = {get_icon: () => 'browser'};
        const {searchBrowserHistory} = load(version, 'browserHistory.js', imports, {
            './utils': {getChromiumProfileDirs: () => [[['one'], app], [['two'], app]]},
            './process': {runJsonScript: () => new Promise(resolve => { completions.push(resolve); })},
        });
        const state = {currentSearchId: 1};
        searchBrowserHistory(state, 1, 'word', () => { calls++; });
        await new Promise(resolve => setImmediate(resolve));
        state.currentSearchId = 2;
        completions.forEach(resolve => resolve([{uri: 'https://example.com', name: 'Site'}]));
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(calls, 0);
        const normal = load(version, 'browserHistory.js', imports, {
            './utils': {getChromiumProfileDirs: () => [[['one'], app], [['two'], app]]},
            './process': {runJsonScript: () => Promise.resolve([{uri: 'https://example.com', name: 'Site'}, null])},
        });
        const results = await new Promise(resolve => normal.searchBrowserHistory(state, 2, 'word', resolve));
        assert.equal(results.length, 1);
    });

    test(`${version}: removal cancels timers and recent files sort newest first`, async () => {
        const GLib = timers();
        const imports = {gi: {GLib}, ui: {
            main: {keybindingManager: {removeHotKey() {}}}, popupMenu: {}, appFavorites: {},
            applet: {TextIconApplet: class {}}, searchProviderManager: {}, settings: {},
        }, misc: {util: {}, gnomeSession: {}, screenSaver: {}, signalManager: {}}};
        const {CanelliaApplet} = load(version, 'applet.js', imports, {}, '\nmodule.exports = {CanelliaApplet};');
        const instance = Object.create(CanelliaApplet.prototype);
        Object.assign(instance, {_timeoutIds: new Set(), willUnmount: false,
            appletSettings: {finalize() {}}, signals: {disconnectAllSignals() {}},
            display: {destroy() {}}, menu: {destroy() {}}});
        let calls = 0;
        instance._scheduleTimeout(10, () => { calls++; });
        instance.on_applet_removed_from_panel();
        instance.on_applet_removed_from_panel();
        await new Promise(resolve => setTimeout(resolve, 20));
        assert.equal(calls, 0);
        assert.equal(GLib.active.size, 0);
        assert.equal(instance._scheduleTimeout(0, () => {}), null);
        instance.recentManagerDefault = {get_items: () => [1, 30, 10].map(time => ({
            get_mime_type: () => 'text/plain', exists: () => true,
            get_display_name: () => 'File ' + time, get_gicon() {},
            get_uri: () => 'file:///file' + time, get_uri_display: () => '', get_modified: () => time,
        }))};
        assert.deepEqual(plain(instance.listRecentByType('all', 2).map(item => item.modifiedTime)), [30, 10]);
    });
}

test('5.8: obsolete folder enumerations complete and close before returning', async () => {
    for (const failure of [false, true]) {
        let closed = 0;
        let completed = 0;
        const enumerator = {
            next_files_async(count, priority, cancel, callback) { setTimeout(() => callback(this, {}), 0); },
            next_files_finish() { completed++; if (failure) throw Error('read failed'); return []; },
            close() { closed++; },
        };
        const Gio = {FileQueryInfoFlags: {NONE: 0}, file_new_for_path: () => ({
            enumerate_children_async(attributes, flags, priority, cancel, callback) { setTimeout(() => callback(this, {}), 0); },
            enumerate_children_finish() { return enumerator; },
        })};
        const imports = {gi: {Gio, GLib: {PRIORITY_DEFAULT: 0}}, ui: {
            main: {}, popupMenu: {}, appFavorites: {}, applet: {TextIconApplet: class {}},
            searchProviderManager: {}, settings: {},
        }, misc: {util: {}, gnomeSession: {}, screenSaver: {}, signalManager: {}}};
        const {CanelliaApplet} = load('5.8', 'applet.js', imports, {}, '\nmodule.exports = {CanelliaApplet};');
        const instance = Object.create(CanelliaApplet.prototype);
        instance.currentCategory = '/different-folder';
        const result = await instance.listFolderAsync('/old-folder');
        assert.equal(result.results.length, 0);
        assert.equal(closed, 1);
        assert.equal(completed, 1);
    }
});

for (const version of ['4.0', '5.8']) {
    test(`${version}: exact names outrank prefixes and ignore accents`, () => {
        const utils = load(version, 'utils.js', {
            gi: {GLib: {get_user_data_dir: () => '/tmp'}, Gio: {}, St: {}, Cinnamon: {}},
            gettext: {bindtextdomain() {}}, mainloop: {}, ui: {main: {}, tweener: {}}, byteArray: {},
        });
        const score = (query, text) => {
            const match = utils.searchStr(query, text);
            return version === '4.0' ? match.score : match;
        };
        assert(score('CALCULADORA', 'Calculadora') > score('CALCULADORA', 'Calculadora avançada'));
        assert(score('EDITOR DE TEXTO', 'Editor de texto') > score('EDITOR DE TEXTO', 'Editor de texto alternativo'));
        assert.equal(score('ACOES', 'Ações'), 1.5);
        assert.equal(score('TEST', ''), 0);
    });
}

for (const version of ['4.0', '5.8']) {
    test(`${version}: Firefox bookmarks work without libgda and tolerate corrupt profile entries`, async () => {
        const appInfo = {get_icon: () => 'browser-icon'};
        const imports = {gi: {Gio: {}, GLib: {}, Cinnamon: {AppSystem: {get_default: () => ({
            lookup_desktop_wmclass: browser => browser === 'firefox' ? {get_app_info: () => appInfo} : null,
        })}}}, misc: {util: {spawn() {}}}, byteArray: {}};
        let calls = 0;
        const {getWebBookmarksAsync} = load(version, 'browserBookmarks.js', imports, {
            './utils': {getChromiumProfileDirs: () => []},
            './process': {runJsonScript: async (script, args, fallback) => {
                calls++;
                assert.equal(script, 'firefoxBookmarks.py');
                assert.deepEqual(plain(args), ['firefox']);
                assert.deepEqual(plain(fallback), []);
                return [{name: 'Personal', uri: 'https://example.com'}, null,
                    {name: 'Unsafe', uri: 'javascript:alert(1)'}];
            }},
        });
        const results = await getWebBookmarksAsync();
        assert.deepEqual(plain(results.map(({name, uri}) => ({name, uri}))), [{name:'Personal', uri:'https://example.com'}]);
        await getWebBookmarksAsync();
        assert.equal(calls, 1);
    });
}

for (const version of ['4.0','5.8']) {
    test(`${version}: favorite insertion, reordering, append and self-drop preserve identities`, () => {
        const imports = {gi:{}, ui:{main:{},popupMenu:{},appFavorites:{},applet:{TextIconApplet:class{}},searchProviderManager:{},settings:{}},misc:{util:{},gnomeSession:{},screenSaver:{},signalManager:{}}};
        const {CanelliaApplet} = load(version,'applet.js',imports,{},'\nmodule.exports={CanelliaApplet};');
        const instance = Object.create(CanelliaApplet.prototype);
        let stored=['one','two'];
        instance.appFavorites={
            _getIds:()=>stored.slice(),
            moveFavoriteToPos(id,pos){stored=stored.filter(value=>value!==id);stored.splice(pos,0,id);},
            addFavoriteAtPos(id,pos){if(!stored.includes(id))stored.splice(pos,0,id);},
        };
        instance.addFavoriteAppToPos('new','two');
        assert.deepEqual(stored,['one','new','two']);
        instance.addFavoriteAppToPos('two','one');
        assert.deepEqual(stored,['two','one','new']);
        instance.addFavoriteAppToPos('two','unknown-target');
        assert.deepEqual(stored,['one','new','two']);
        instance.addFavoriteAppToPos('new','new');
        assert.deepEqual(stored,['one','new','two']);
        assert.equal(new Set(stored).size,stored.length);
    });
}

for (const version of ['4.0','5.8']) {
    test(`${version}: blank, missing and escaped tooltip text remains safe`, () => {
        const utils=load(version,'utils.js',{
            gi:{GLib:{get_user_data_dir:()=>'/tmp'},Gio:{},St:{},Cinnamon:{}},
            gettext:{bindtextdomain(){}},mainloop:{},ui:{main:{},tweener:{}},byteArray:{},
        });
        for(const value of ['',null,undefined]) assert.equal(utils.wordWrap(value),'');
        assert.equal(utils.wordWrap('A < B & C'),'A < B & C');
        assert.equal(utils.wordWrap('A'.repeat(300)).replace(/\n/g,''),'A'.repeat(300));
    });
}
