#!/usr/bin/env python3
"""Measure synchronous menu work in Cinnamon; restore state and never launch apps.

Samples measure CPU work through Cinnamon's Eval API, not rendered frame latency.
Use the same host, installed source and workload for before/after comparisons.
"""
import argparse
import json
from pathlib import Path
import statistics
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
        success, output = proxy.call_sync('Eval', GLib.Variant('(s)', (code,)),
            Gio.DBusCallFlags.NONE, 20000, None).unpack()
        if not success:
            raise RuntimeError(output)
        result = json.loads(output)
        if isinstance(result, dict) and 'error' in result:
            raise RuntimeError(str(result))
        return result

    prefix = 'const a=global.__canelliaPerformance.applet;const v=a.display.appsView;'
    report = {'sample_type': 'synchronous CPU work in Cinnamon', 'metrics': {}}
    setup = False
    try:
        report['environment'] = evaluate('''const d=imports.ui.appletManager.getAppletDefinition({applet_id:''' + json.dumps(args.instance) + '''});
            if(!d || !d.applet) throw new Error('Applet is not loaded');
            const a=d.applet;
            global.__canelliaPerformance={applet:a,category:a.currentCategory,open:a.menu.isOpen,
                search:a.display.searchView.searchEntry.get_text()};
            a.menu.close(false);a.menu.open(false);a._endSearchMode();a.setActiveCategory('all');
            a.menu.close(false);a.setActiveCategory('all');
            return {apps:a.apps.listApplications('all').length,categories:a.display.categoriesView.buttons.length,
                buttons:a.display.appsView.buttonStore.length};''')
        setup = True
        jobs = {
            'active_buttons_1000': 'for(let i=0;i<1000;i++)v.getActiveButtons();',
            'search_100': "for(let i=0;i<100;i++)a.apps.searchApplications(['EDITOR','FIREFOX','CONFIG','TERMINAL','ZZZXQ'][i%5]);",
            'grid_height_100': 'for(let i=0;i<100;i++)v.syncGridHeight();',
            'category_changes_30': "const ids=a.display.categoriesView.buttons.filter(b=>!b.id.startsWith('/')).map(b=>b.id);for(let i=0;i<30;i++)a.setActiveCategory(ids[i%ids.length]);a.setActiveCategory('all');",
            'open_close_20': "for(let i=0;i<20;i++){a.menu.open(false);a.menu.close(false);}",
        }
        for name, body in jobs.items():
            samples = []
            for repetition in range(8):
                duration = evaluate(prefix + 'const start=imports.gi.GLib.get_monotonic_time();' + body +
                    'return (imports.gi.GLib.get_monotonic_time()-start)/1000;')
                if repetition:
                    samples.append(duration)
                time.sleep(.05)
            report['metrics'][name] = {'median_ms': statistics.median(samples), 'samples_ms': samples}
            print(name, report['metrics'][name]['median_ms'], flush=True)
        report['retention'] = evaluate(prefix + '''a.setActiveCategory('all');const before=v.buttonStore.length;
            for(let i=0;i<60;i++){a.setActiveCategory('all');a.menu.open(false);a.menu.close(false);}
            const after=v.buttonStore.length;
            if(before!==after)throw new Error('Button cache grew across repeated cycles');
            return {cycles:60,before,after};''')
    finally:
        if setup:
            evaluate('''const s=global.__canelliaPerformance,a=s.applet;a._endSearchMode();
                a.setActiveCategory(s.category);a.menu.close(false);
                if(s.open){a.menu.open(false);a.display.searchView.searchEntry.set_text(s.search);}
                delete global.__canelliaPerformance;return true;''')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
