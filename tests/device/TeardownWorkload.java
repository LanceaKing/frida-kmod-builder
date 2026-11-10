package re.frida.test;
import java.lang.reflect.Method;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
public final class TeardownWorkload {
  public static final AtomicInteger alive = new AtomicInteger();
  public static final AtomicLong calls = new AtomicLong();
  public static final AtomicLong failures = new AtomicLong();
  public static volatile boolean running;
  public static void start(final int count, final long durationMs, final String output) throws Exception {
    if (alive.get() != 0) throw new IllegalStateException("already running");
    calls.set(0); failures.set(0); running = true;
    final Method method = System.class.getDeclaredMethod("identityHashCode", Object.class);
    final long deadline = System.nanoTime() + durationMs * 1000000L;
    for (int i=0; i<count; i++) {
      alive.incrementAndGet();
      new Thread(new Runnable() { public void run() {
        try {
          final Object object = new Object();
          final int expected = System.identityHashCode(object);
          while (running && System.nanoTime() < deadline) {
            int actual = ((Integer)method.invoke(null, object)).intValue();
            if (actual != expected) failures.incrementAndGet();
            calls.incrementAndGet();
          }
        } catch (Throwable e) { failures.incrementAndGet(); }
        finally {
          if (alive.decrementAndGet() == 0) {
            try {
              java.io.FileOutputStream stream = new java.io.FileOutputStream(output);
              String result = "{\"calls\":" + calls.get() + ",\"failures\":" + failures.get() + "}";
              stream.write(result.getBytes("UTF-8")); stream.close();
            } catch (Exception e) { System.out.println("teardown probe output error: " + e); }
          }
        }
      }}, "frida-teardown-probe").start();
    }
  }
  public static void stop() { running=false; }
}
