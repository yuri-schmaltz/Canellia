const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const root = path.resolve(__dirname, '..');
function load(version, name, extra = '') {
    const context = vm.createContext({module: {exports: {}}, require: () => ({}),
        imports: {gi: {GLib: {get_user_data_dir: () => '/tmp'}, Pango: {}, Gio: {}, St: {}, Cinnamon: {}},
            gettext: {bindtextdomain() {}}, mainloop: {}, byteArray: {},
            ui: {main: {}, tweener: {}, dnd: {}}, misc: {util: {}, signalManager: {}}},
        global: {ui_scale: 1}, __meta: {}});
    vm.runInContext(fs.readFileSync(path.join(root, 'Canellia@json', version, name), 'utf8') + extra, context);
    return context.module.exports;
}
for (const version of ['4.0', '5.8']) {
    test(`${version}: optimized search preserves frozen scoring and markup`, () => {
        const utils = load(version, 'utils.js');
        const reference = {module: {exports: {}},
            graphemeBaseChars: utils.graphemeBaseChars,
            escapeRegExp: text => text.replace(/[-\/.*+?^${}()|[\]\\]/g, '\\$&')};
        vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'fixtures', 'search-reference-' + version + '.js'), 'utf8'), reference);
        const strings = ['', 'Ações', 'Editor de texto', 'Calculadora avançada', 'foo.bar [test]',
            'line\nbreak', 'straße', 'İstanbul', 'emoji 🌷', 'e\u0301', '中文', 'Σίγμα', '\\path/with+symbols',
            'A < B & C', 'a'.repeat(5000)];
        for (let i = 0; i < 40; i++) strings.push(`Example ${i} ${strings[i % 14]}`);
        const queries = ['', 'ACOES', 'EDITOR', 'EDITOR DE TEXTO', 'CALC', 'STRASSE', 'ZZZXQ',
            '[', '.', '*', '\\', '+', 'A <', '🌷', '中文', 'ΣΙΓΜΑ'];
        for (const query of queries) for (const text of strings) for (const fuzzy of [false, true]) for (const substring of [false, true]) {
            const expected = reference.module.exports.searchStr(query, text, fuzzy, substring);
            // Repeat to cover global regex reuse and cache hits.
            for (let repetition = 0; repetition < 2; repetition++) {
                assert.equal(JSON.stringify(utils.searchStr(query, text, fuzzy, substring)), JSON.stringify(expected),
                    JSON.stringify({query, text, fuzzy, substring}));
            }
        }
    });
    test(`${version}: search caches remain bounded across thousands of inputs`, () => {
        const utils = load(version, 'utils.js', '\nmodule.exports.caches={texts:normalizedSearchText,queries:preparedSearchQueries};');
        for (let i = 0; i < 2000; i++) utils.searchStr('QUERY' + i, 'Application ' + i);
        assert(utils.caches.texts.size <= 512);
        assert(utils.caches.queries.size <= 64);
        utils.searchStr('QUERY', 'x'.repeat(5000));
        assert(!utils.caches.texts.has('x'.repeat(5000)));
    });
    test(`${version}: active buttons preserve order without Clutter queries`, () => {
        const {AppsView} = load(version, 'appsview.js');
        const view = Object.create(AppsView.prototype);
        const a = {}, b = {}, heading = {};
        const first = {actor: a}, second = {actor: b};
        view._buttonsByActor = new WeakMap([[a, first], [b, second]]);
        view.buttonStore = {find() { throw Error('Linear cache scan'); }};
        view._activeButtons = [second, first];
        view.getActiveContainer = () => { throw Error('Unnecessary Clutter query'); };
        const active = view.getActiveButtons();
        assert.equal(active[0], second);
        assert.equal(active[1], first);
        assert.equal(active.length, 2);
        active.pop();
        assert.equal(view.getActiveButtons().length, 2);
    });
    test(`${version}: temporary result cleanup releases both caches and active references`, () => {
        const {AppsView} = load(version, 'appsview.js');
        const view = Object.create(AppsView.prototype);
        let destroyed = 0;
        const temporary = {actor: {}, app: {deleteAfterUse: true}, destroy() { destroyed++; }};
        const retained = {actor: {}, app: {}};
        view.buttonStore = [temporary, retained];
        view._activeButtons = [temporary, retained];
        view._buttonsByApp = new WeakMap([[temporary.app, temporary], [retained.app, retained]]);
        view._buttonsByActor = new WeakMap([[temporary.actor, temporary], [retained.actor, retained]]);
        view.buttonStoreCleanup();
        assert.equal(destroyed, 1);
        assert.equal(view.buttonStore.length, 1);
        assert.equal(view.getActiveButtons()[0], retained);
        assert(!view._buttonsByActor.has(temporary.actor));
        assert(!view._buttonsByApp.has(temporary.app));
    });
    test(`${version}: initial grid geometry stays finite before width allocation`, () => {
        const {AppsView} = load(version, 'appsview.js');
        const view = Object.create(AppsView.prototype);
        view.applet = view.appThis = {display: {}, settings: {appsGridIconSize: 64}};
        for (const width of [undefined, NaN, 0, 500]) {
            view.currentGridBoxWidth = width;
            view.applet.display.currentGridBoxUsableWidth = width;
            const grid = view.getGridValues();
            assert(grid.columns >= 1);
            assert(Number.isFinite(grid.columnWidth));
            assert(grid.columnWidth >= 1);
        }
    });
    test(`${version}: grid fills viewport, reuses measurements and invalidates changed content`, () => {
        const {AppsView} = load(version, 'appsview.js');
        const view = Object.create(AppsView.prototype);
        const settings = {settings: {applicationsViewMode: 1}};
        view.applet = view.appThis = settings;
        view._buttonsByActor = new WeakMap();
        view._gridRevision = 0;
        const node = {adjust_for_height: height => height, get_length: () => 0};
        const actors = [];
        for (let i = 0; i < 6; i++) {
            const label = {value: 'app ' + i, get_text() { return this.value; }};
            const actor = {height: 100, width: 150, layout_row: Math.floor(i / 3), node: {}, measured: 0, writes: 0,
                get_theme_node() { return this.node; },
                get_preferred_height() { this.measured++; return [100, 100]; },
                set_height(height) { this.writes++; this.height = height === -1 ? 100 : height; }};
            actors.push(actor);
            view._buttonsByActor.set(actor, {label});
        }
        view.applicationsGridLayout = {get_children: () => actors, layout_manager: {row_spacing: 0}};
        view.applicationsScrollBox = {height: 499, get_theme_node: () => node};
        view.applicationsGridBox = view.applicationsBoxWrapper = {get_theme_node: () => node};
        view.headerText = {visible: false};
        view.syncGridHeight();
        assert.equal(actors[0].height + actors[3].height, 499);
        const writes = actors.map(actor => actor.writes);
        for (let i = 0; i < 100; i++) view.syncGridHeight();
        assert.deepEqual(actors.map(actor => actor.writes), writes);
        assert(actors.every(actor => actor.measured === 1));
        actors[0].width = 200;
        actors[1].node = {};
        view._buttonsByActor.get(actors[2]).label.value = 'new title';
        view._gridRevision++; // Population and theme events invalidate the complete layout.
        view.syncGridHeight();
        assert.deepEqual(actors.map(actor => actor.measured), [2, 2, 2, 2, 2, 2]);
        view.applicationsScrollBox.height = 150;
        view.syncGridHeight();
        assert(actors.every(actor => actor.height === 100)); // Scroll instead of clipping.
        view.applicationsScrollBox.height = 620;
        view.syncGridHeight();
        assert.equal(actors[0].height + actors[3].height, 620);
    });
}

for (const version of ['4.0', '5.8']) {
    test(`${version}: population reuse refreshes changed catalogs, layout and transient sources`, () => {
        const {AppsView} = load(version, 'appsview.js');
        const view = Object.create(AppsView.prototype);
        view.applet = view.appThis = {settings: {applicationsViewMode: 1}};
        let columns = 3, syncs = 0;
        view.getGridValues = () => ({columns, columnWidth: 150});
        view.leaveAppsViewFocusedActor = view.clearAppsViewFocusedActors = () => {};
        view.syncGridHeight = () => { syncs++; };
        const apps = [{isApplication: true}, {isApplication: true}];
        view._rememberPopulation([[apps, null]], null);
        assert(view._reusePopulation([[apps, null]], null));
        assert.equal(syncs, 1);
        assert(!view._reusePopulation([[apps.slice(), null]], null));
        assert(!view._reusePopulation([[apps, 'New heading']], null));
        apps.push({isApplication: true});
        assert(!view._reusePopulation([[apps, null]], null));
        apps.pop();
        columns = 4;
        assert(!view._reusePopulation([[apps, null]], null));
        columns = 3;
        view.applet.settings.applicationsViewMode = 0;
        assert(!view._reusePopulation([[apps, null]], null));
        view.applet.settings.applicationsViewMode = 1;
        view._rememberPopulation([[[{isApplication: true, deleteAfterUse: true}], null]], null);
        assert.equal(view._populationSignature, null);
    });
}
