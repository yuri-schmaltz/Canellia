// Python helpers use an explicit interpreter, bounded lifetime and JSON contract.
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;

function runJsonScript(script, args, fallback, timeoutMs = 10000) {
    return new Promise(resolve => {
        let process = null;
        let timeout = 0;
        let settled = false;
        const cancellable = new Gio.Cancellable();
        const finish = value => {
            if (settled) return;
            settled = true;
            if (timeout) {
                GLib.source_remove(timeout);
                timeout = 0;
            }
            resolve(value);
        };
        try {
            process = Gio.Subprocess.new(
                ['python3', GLib.build_filenamev([__meta.path, script])].concat(args),
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            );
            timeout = GLib.timeout_add(GLib.PRIORITY_DEFAULT, timeoutMs, () => {
                timeout = 0;
                finish(fallback);
                cancellable.cancel();
                process.force_exit();
                return GLib.SOURCE_REMOVE;
            });
            process.communicate_utf8_async(null, cancellable, (object, result) => {
                try {
                    const [success, stdout, stderr] = object.communicate_utf8_finish(result);
                    if (settled) return;
                    if (!success || !object.get_successful()) {
                        throw new Error(`${script} failed: ${stderr || 'no diagnostic'}`);
                    }
                    const value = JSON.parse(stdout);
                    const valid = Array.isArray(fallback) ? Array.isArray(value) :
                        value !== null && typeof value === 'object' && !Array.isArray(value);
                    if (!valid) throw new Error(`${script} returned an invalid JSON type`);
                    finish(value);
                } catch (error) {
                    if (!settled) global.logWarning(`Canellia: ${error.message}`);
                    finish(fallback);
                }
            });
        } catch (error) {
            if (process) process.force_exit();
            global.logWarning(`Canellia: ${error.message}`);
            finish(fallback);
        }
    });
}

module.exports = {runJsonScript};
