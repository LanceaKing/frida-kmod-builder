import Java from 'frida-java-bridge';

let workload;
let output;
let hits = 0;
let objectCalls = 0;
let pendingObjectCalls = 0;
const usleep = new NativeFunction(Process.getModuleByName('libc.so').getExportByName('usleep'), 'int', ['uint']);

rpc.exports = {
  prepare(data, token) {
    return new Promise((resolve, reject) => Java.perform(() => {
      try {
        const app = Java.use('android.app.ActivityThread').currentApplication();
        const cache = app.getCacheDir().getAbsolutePath().toString();
        const path = `${cache}/frida-teardown-${token}.dex`;
        output = `${cache}/frida-teardown-${token}.json`;
        const file = new File(path, 'wb');
        file.write(new Uint8Array(data).buffer);
        file.close();
        Java.openClassFile(path).load();
        workload = Java.use('re.frida.test.TeardownWorkload');
        const identity = Java.use('java.lang.System').identityHashCode.overload('java.lang.Object');
        identity.implementation = function (object) {
          hits++;
          return identity.call(this, object);
        };
        const echo = workload.echo;
        echo.implementation = function (object) {
          pendingObjectCalls++;
          try {
            usleep(20000);
            objectCalls++;
            return object;
          } finally {
            pendingObjectCalls--;
          }
        };
        // Populate the object-return type's cached JNI class wrapper before unload.
        workload.echo(workload.$new());
        resolve({path, output});
      } catch (error) {
        reject(error);
      }
    }));
  },
  start() {
    Java.performNow(() => workload.start(4, 2500, output));
  },
  counts() {
    let result;
    Java.performNow(() => {
      result = {
        hits,
        objectCalls,
        pendingObjectCalls,
        calls: workload.calls.value.get().toString(),
        alive: workload.alive.value.get(),
        failures: workload.failures.value.get().toString()
      };
    });
    return result;
  }
};
