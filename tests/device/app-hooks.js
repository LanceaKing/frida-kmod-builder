import Java from 'frida-java-bridge';

// Observation-only probes: preserve both the native and Java return values.
const events = {native: 0, java: 0};
const getpidAddress = Process.getModuleByName('libc.so').getExportByName('getpid');
const getpid = new NativeFunction(getpidAddress, 'int', []);
const nativeHook = Interceptor.attach(getpidAddress, {
  onLeave(retval) {
    events.native++;
    if (events.native <= 3) send({kind: 'native', name: 'getpid', original: retval.toInt32()});
  }
});
send({kind: 'native-ready', pid: Process.id, returned: getpid()});
Java.perform(() => {
  const System = Java.use('java.lang.System');
  const identity = System.identityHashCode.overload('java.lang.Object');
  identity.implementation = function (object) {
    const original = identity.call(this, object);
    events.java++;
    if (events.java <= 3) send({kind: 'java', name: 'System.identityHashCode', original});
    return original;
  };
  const object = Java.use('java.lang.Object').$new();
  const returned = System.identityHashCode(object);
  send({kind: 'java-ready', returned, hits: events.java});
});
rpc.exports = {counts() { return events; }};
