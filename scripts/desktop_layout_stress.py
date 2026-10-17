#!/usr/bin/env python3
"""Stress the installed menu's layouts and caches; restore settings and pointer.

Never activates applications, saves menu edits or removes installations.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
from gi.repository import Gio, GLib


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--instance', default='15')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    proxy = Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE,
        None, 'org.Cinnamon', '/org/Cinnamon', 'org.Cinnamon', None)

    def evaluate(body):
        code = '(()=>{try{' + body + '}catch(e){return {error:String(e),stack:e.stack};}})()'
        ok, result = proxy.call_sync('Eval', GLib.Variant('(s)', (code,)), Gio.DBusCallFlags.NONE, 20000, None).unpack()
        if not ok:
            raise RuntimeError(result)
        data = json.loads(result)
        if isinstance(data, dict) and 'error' in data:
            raise RuntimeError(str(data))
        return data

    prefix = 'const a=global.__canelliaLayoutStress.applet;const v=a.display.appsView;const c=a.display.categoriesView;'
    report = {'checks': []}
    setup = False

    def check(name, body, settle=False):
        if settle:
            time.sleep(.4)
        result = evaluate(prefix + body)
        report['checks'].append({'name': name, 'result': result})
        print(name + ': OK', flush=True)
        return result

    try:
        evaluate('''const d=imports.ui.appletManager.getAppletDefinition({applet_id:''' + json.dumps(args.instance) + '''});
            if(!d || !d.applet)throw new Error('Applet is not loaded');const a=d.applet;
            global.__canelliaLayoutStress={applet:a,category:a.currentCategory,search:a.display.searchView.searchEntry.get_text(),
                open:a.menu.isOpen,mode:a.settings.applicationsViewMode,width:a.settings.customMenuWidth,
                height:a.settings.customMenuHeight,resizing:a.resizer.resizingInProgress,pointer:global.get_pointer()};
            return true;''')
        setup = True
        subprocess.run(['xdotool', 'mousemove', '0', '0'], check=True)
        check('grid_mode', '''if(a.settings.applicationsViewMode!==1){a.settings.applicationsViewMode=1;
            for(const binding of a.appletSettings.bindings['applications-view-mode'])if(binding.callback)binding.callback();}
            a.menu.open(false);a._endSearchMode();a.setActiveCategory('all');return true;''')
        time.sleep(.4)
        for count in (1, 2, 3, 4, 7, 10, 20, 99):
            check('populate_' + str(count), 'v.populate(a.apps.listApplications("all").slice(0,' + str(count) + '));return true;')
            check('geometry_' + str(count), '''const buttons=v.getActiveButtons();const columns=v.getGridValues().columns;
                const boxes=buttons.map(b=>b.actor.get_allocation_box());
                if(buttons.length!==''' + str(count) + ''')throw new Error('Wrong active count');
                if(boxes.some(b=>!Number.isFinite(b.y2)))throw new Error('Invalid allocation');
                const bottom=Math.max(...boxes.map(b=>b.y2));
                if(buttons.length<=columns*3 && Math.abs(bottom-v.applicationsScrollBox.height)>2)
                    throw new Error('Unused vertical space');
                return {count:buttons.length,columns,bottom,viewport:v.applicationsScrollBox.height};''', True)
        check('duplicate_actor', '''const item=a.apps.listApplications('all')[0];v.populate([item,item]);
            if(v.getActiveButtons().length!==1)throw new Error('Duplicate active actor');return {unique:true};''')
        check('categories_remove', '''global.__canelliaLayoutStress.buttons=c.buttons.slice();
            const last=c.buttons.pop();c.categoriesBox.remove_child(last.actor);c.syncHeight();return true;''')
        check('categories_fill_after_remove', '''const last=c.buttons[c.buttons.length-1].actor.get_allocation_box();
            if(Math.abs(last.y2-c.categoriesBox.height)>2)throw new Error('Categories leave a gap');
            return {count:c.buttons.length,bottom:last.y2};''', True)
        check('categories_restore', '''const saved=global.__canelliaLayoutStress.buttons;c.buttons=saved;
            c.categoriesBox.remove_all_children();c.buttons.forEach(b=>c.categoriesBox.add(b.actor,{y_fill:true}));
            c.syncHeight();delete global.__canelliaLayoutStress.buttons;return true;''')
        check('resize', '''a.resizer.resizingInProgress=true;v.populate(a.apps.listApplications('all').slice(0,7));
            a.display.onMenuResized(700*global.ui_scale,680*global.ui_scale);return true;''')
        check('resize_geometry', '''const columns=v.getGridValues().columns;
            const last=c.buttons[c.buttons.length-1].actor.get_allocation_box();
            if(Math.abs(last.y2-c.categoriesBox.height)>2)throw new Error('Category resizing failed');
            if(Math.abs(v.applicationsGridLayout.height-v.applicationsScrollBox.height)>2)throw new Error('Grid resizing failed');
            return {columns,height:v.applicationsGridLayout.height};''', True)
        check('cache_stress_start', "a.menu.close(false);a.setActiveCategory('all');global.__canelliaLayoutStress.cacheBefore=v.buttonStore.length;return true;")
        for cycle in range(6):
            check('cache_cycle_' + str(cycle), """const items=Array.from({length:5000},(_,i)=>({name:'Stress '+i,
                isSearchResult:true,deleteAfterUse:true,gicon:new imports.gi.Gio.ThemedIcon({name:'application-x-executable'}),
                activate:()=>{throw new Error('Must not execute');}}));v.populate(items);return true;""")
            for page in range(10):
                check('cache_page_' + str(cycle) + '_' + str(page), """const before=global.__canelliaLayoutStress.cacheBefore;
                    if(v.getActiveButtons().length!==200)throw new Error('Pagination limit failed');
                    if(v.buttonStore.length>before+200)throw new Error('Temporary buttons accumulate');
                    if(!v.changePage(1))throw new Error('Next page unavailable');return true;""")
            check('cache_cleanup_' + str(cycle), 'v.clearAppsView();v.buttonStoreCleanup();return true;')
        check('cache_retention', """const before=global.__canelliaLayoutStress.cacheBefore;
            if(v.buttonStore.length!==before)throw new Error('Temporary cache was not released');
            a.setActiveCategory('all');return {cycles:6,resultsPerCycle:5000,pagesPerCycle:10,
                buttonsBefore:before,buttonsAfter:v.buttonStore.length};""")
        check('list_mode', '''a.settings.applicationsViewMode=0;
            for(const binding of a.appletSettings.bindings['applications-view-mode'])if(binding.callback)binding.callback();
            return true;''')
        time.sleep(.4)
        check('list_mode_population', "a.setActiveCategory('Office');return true;")
        # Fetch the new AppsView after the mode callback recreated the display.
        check('list_mode_geometry', '''if(v.getActiveContainer()!==v.applicationsListBox)throw new Error('List mode uses wrong container');
            if(v.getActiveButtons().length!==a.apps.listApplications('Office').length)throw new Error('List mode count failed');
            return {items:v.getActiveButtons().length};''', True)
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error)
        raise
    finally:
        if setup:
            restored = evaluate('''const s=global.__canelliaLayoutStress,a=s.applet;
                if(s.buttons){const c=a.display.categoriesView;c.buttons=s.buttons;c.categoriesBox.remove_all_children();
                    c.buttons.forEach(b=>c.categoriesBox.add(b.actor,{y_fill:true}));c.syncHeight();}
                a._endSearchMode();a.menu.close(false);
                if(a.settings.applicationsViewMode!==s.mode){a.settings.applicationsViewMode=s.mode;
                    for(const binding of a.appletSettings.bindings['applications-view-mode'])if(binding.callback)binding.callback();}
                return s.pointer;''')
            time.sleep(.4)
            evaluate("""const s=global.__canelliaLayoutStress,a=s.applet;a.resizer.resizingInProgress=true;
                a.display.updateMenuSize(s.width*global.ui_scale,s.height*global.ui_scale);
                if(s.mode===1)a.display.appsView.resizeGrid();a.resizer.resizingInProgress=s.resizing;
                a.setActiveCategory(s.category);if(s.open){a.menu.open(false);a.display.searchView.searchEntry.set_text(s.search);}
                delete global.__canelliaLayoutStress;return true;""")
            subprocess.run(['xdotool', 'mousemove', str(restored[0]), str(restored[1])], check=True)
            report['restored'] = True
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
