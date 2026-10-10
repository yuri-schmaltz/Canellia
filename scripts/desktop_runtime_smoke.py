#!/usr/bin/env python3
"""Exercise the installed applet in Cinnamon; restore preferences in finally.

Launches only /usr/bin/true. Favorites are read-only. Run using host PyGObject.
"""
import argparse
import json
from pathlib import Path
import time
import subprocess
from gi.repository import Gio, GLib


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--instance', default='15')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    proxy = Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE,
        None, 'org.Cinnamon', '/org/Cinnamon', 'org.Cinnamon', None)
    def evaluate(body):
        success, result = proxy.call_sync('Eval', GLib.Variant('(s)', ('(()=>{try{' + body + '}catch(error){return {__error:String(error),stack:error.stack};}})()',)),
            Gio.DBusCallFlags.NONE, 20000, None).unpack()
        if not success:
            raise RuntimeError(result)
        result = json.loads(result)
        if isinstance(result, dict) and '__error' in result:
            raise RuntimeError(result['__error'] + '\n' + result.get('stack', ''))
        return result
    identifier = json.dumps(str(args.instance))
    report = {'tests': [], 'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    def check(name, body):
        result = evaluate('const a=global.__canelliaGauntlet.applet;' + body)
        report['tests'].append({'name': name, 'result': result})
        print(name + ': OK')
    def wait_for(body):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if evaluate('const a=global.__canelliaGauntlet.applet;' + body):
                return
            time.sleep(0.1)
        raise RuntimeError('Asynchronous menu update timed out')
    setup = False
    try:
        evaluate('''const definition=imports.ui.appletManager.getAppletDefinition({applet_id:''' + identifier + '''});
            if (!definition || definition.real_uuid !== 'Canellia@json') throw new Error('Canellia is not loaded');
            const a=definition.applet;
            global.__canelliaGauntlet={applet:a,category:a.currentCategory,search:a.display.searchView.searchEntry.get_text(),
                open:a.menu.isOpen,width:a.settings.customMenuWidth,height:a.settings.customMenuHeight,
                favorites:global.settings.get_strv('favorite-apps')};
            return {loaded:true};''')
        setup = True
        check('open_and_grid', '''a.menu.open(false);a.setActiveCategory('all');
            const grid=a.display.appsView.getGridValues();
            if(!a.menu.isOpen || grid.columns<1 || !Number.isFinite(grid.columnWidth)) throw new Error('Invalid menu grid');
            return {columns:grid.columns,visible:a.display.appsView.getActiveButtons().length};''')
        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+f'], check=True)
        check('keyboard_search_focus', "const focus=global.stage.get_key_focus(),view=a.display.searchView;if(focus!==view.searchEntry && focus!==view.searchEntryText) throw new Error('Ctrl+F did not focus search');return {focused:true};")
        check('exact_application_search', '''const apps=a.apps.listApplications('all');
            if(!apps.length) throw new Error('No installed applications');
            const name=apps[0].name;
            const pattern=name.normalize('NFKD').replace(/[\\u0300-\\u036f]/g,'').toLocaleUpperCase();
            const results=a.apps.searchApplications(pattern).sort((x,y)=>y.score-x.score);
            if(!results.some(app=>app.name===name && app.score>=1.5)) throw new Error('Exact search failed');
            return {matches:results.length};''')
        check('calculator_query', "a.display.searchView.searchEntry.set_text('2+3*4');return {requested:true};")
        wait_for("return a.display.appsView.getActiveButtons().some(button=>button.app.name.includes('14'));")
        check('calculator_result', '''const names=a.display.appsView.getActiveButtons().map(button=>button.app.name);
            if(!names.some(name=>name.includes('14'))) throw new Error('Calculator result missing');
            return {result:14};''')
        check('no_results_query', "a.display.searchView.searchEntry.set_text('zzzz_canellia_nonexistent_874621');return {requested:true};")
        wait_for("return a.display.appsView.getActiveButtons().length===0 && (/resultado|No results/i).test(a.display.appsView.headerText.get_text());")
        check('no_results_status', '''if(a.display.appsView.getActiveButtons().length!==0) throw new Error('Unexpected search result');
            if(!a.display.appsView.headerText.get_text()) throw new Error('Missing empty-search explanation');
            return {message:a.display.appsView.headerText.get_text()};''')
        check('pagination_and_button_execution', '''a._endSearchMode();a.setActiveCategory('all');
            const items=Array.from({length:450},(_,i)=>({name:'Canellia test '+i,description:'Safe test <&>',
                isSearchResult:true,deleteAfterUse:true,gicon:new imports.gi.Gio.ThemedIcon({name:'application-x-executable'}),
                activate:()=>{global.__canelliaGauntlet.launched=imports.gi.Gio.AppInfo.create_from_commandline('/usr/bin/true','Canellia test',0).launch([],null);}}));
            a.display.appsView.populate(items);
            if(a.display.appsView.getActiveButtons().length!==200) throw new Error('Page limit failed');
            if(!a.display.appsView.changePage(1)) throw new Error('Page navigation unavailable');
            if(a.display.appsView.getActiveButtons()[0].app.name!=='Canellia test 200') throw new Error('Next page failed');
            a.display.appsView.subheadings[a.display.appsView.subheadings.length-1].clickAction();
            if(a.display.appsView.getActiveButtons().length!==50) throw new Error('Last page failed');
            if(a.display.appsView.changePage(1)) throw new Error('Moved beyond last page');
            if(!a.display.appsView.changePage(-1)) throw new Error('Previous page failed');
            // Use the actual first button's activation path; it runs only true.
            a.display.appsView.getActiveButtons()[0].activate();
            if(!global.__canelliaGauntlet.launched) throw new Error('Safe launcher activation failed');
            a.display.appsView.clearAppsView();a.display.appsView.buttonStoreCleanup();
            return {total:450,page:200,launched:true};''')
        check('repeated_open_close_and_favorites', '''const before=a.display.appsView.buttonStore.length,start=Date.now();for(let i=0;i<12;i++){a.menu.open(false);a.setActiveCategory('all');a.menu.close(false);}
            const original=global.__canelliaGauntlet.favorites,current=global.settings.get_strv('favorite-apps');
            if(JSON.stringify(original)!==JSON.stringify(current)) throw new Error('Favorites unexpectedly changed');
            const ids=a.appFavorites.getFavorites().map(app=>app.get_id());
            const after=a.display.appsView.buttonStore.length;
            if(after!==before) throw new Error('Button cache grows across identical cycles');
            return {cycles:12,favorites:ids.length,stored:current.length,buttons:after,duration_ms:Date.now()-start};''')
        evaluate('global.__canelliaGauntlet.applet.menu.open(false);return true;')
        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Escape'], check=True)
        wait_for('return !a.menu.isOpen;')
        check('keyboard_escape', "if(a.menu.isOpen) throw new Error('Escape did not close menu');return {closed:true};")
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error)
        raise
    finally:
        if setup:
            evaluate('''const original=global.__canelliaGauntlet,a=original.applet;
                a._endSearchMode();a.currentCategory=original.category;a.menu.close(false);
                a.settings.customMenuWidth=original.width;a.settings.customMenuHeight=original.height;
                a.setActiveCategory(original.category);
                if(original.open){a.menu.open(false);a.display.searchView.searchEntry.set_text(original.search);}
                delete global.__canelliaGauntlet;return {restored:true};''')
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
