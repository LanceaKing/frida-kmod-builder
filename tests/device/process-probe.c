/* Disposable arm64 process probe for Frida 17.26.2's official prctl ABI.
 * Compile with the Android NDK, run `target` as shell, and run `control PID
 * ENTRY` as root. The child entry uses only syscalls, not an invented libc TLS.
 */
#include <errno.h>
#include <inttypes.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

#define MAGIC 0x46524944UL
#define TOKEN 0x1d5f9e6b2c7a4038ULL
struct alloc_args { uint64_t size; uint32_t pid, prot; };
struct free_args { uint64_t address, size; uint32_t pid; };
struct xfer_args { uint64_t address, buffer, size; uint32_t pid; };
struct spawn_args { uint64_t entry, stack, arg, tls; uint32_t pid; };
struct report { uint64_t pid, tid, uid, tls, done, release; };

__attribute__((naked, used)) static void probe_entry(void *arg) {
    __asm__ volatile (
        "mov x19, x0\n"
        "mov x8, #172\nsvc #0\nstr x0, [x19]\n"
        "mov x8, #178\nsvc #0\nstr x0, [x19, #8]\n"
        "mov x8, #174\nsvc #0\nstr x0, [x19, #16]\n"
        "mrs x0, tpidr_el0\nstr x0, [x19, #24]\n"
        "mov x0, #1\nadd x1, x19, #32\nstlr x0, [x1]\n"
        "sub sp, sp, #16\nstr xzr, [sp]\n"
        "mov x0, #0x9680\nmovk x0, #0x98, lsl #16\nstr x0, [sp, #8]\n"
        "1: add x1, x19, #40\nldar x0, [x1]\ncbnz x0, 2f\n"
        "mov x0, sp\nmov x1, #0\nmov x8, #101\nsvc #0\nb 1b\n"
        "2: mov x0, #0\nmov x8, #93\nsvc #0\nbrk #0\n");
}
static long control(unsigned op, void *args) {
    return syscall(__NR_prctl, MAGIC, (unsigned long)op, args, 0UL, TOKEN);
}
static uint64_t allocate(pid_t pid, size_t size) {
    struct alloc_args args = { size, (uint32_t)pid, PROT_READ | PROT_WRITE };
    long result = control(64, &args);
    return result > 0 ? (uint64_t)result : 0;
}
static int transfer(pid_t pid, uint64_t address, void *buffer, size_t size, int write) {
    struct xfer_args args = {address, (uintptr_t)buffer, size, (uint32_t)pid};
    return control(write ? 66 : 67, &args) == (long)size ? 0 : -1;
}
static int release(pid_t pid, uint64_t address, size_t size) {
    struct free_args args = {address, size, (uint32_t)pid};
    return control(65, &args);
}
int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "target")) {
        uintptr_t tls;
        __asm__("mrs %0, tpidr_el0" : "=r"(tls));
        printf("{\"pid\":%d,\"uid\":%d,\"entry\":\"0x%" PRIxPTR "\",\"main_tls\":\"0x%" PRIxPTR "\"}\n",
               getpid(), getuid(), (uintptr_t)probe_entry, tls);
        fflush(stdout);
        for (;;) pause();
    }
    if (argc == 2 && !strcmp(argv[1], "ping")) {
        long result = control(32, NULL);
        printf("{\"ping\":%ld,\"errno\":%d}\n", result, errno);
        return result == MAGIC ? 0 : 1;
    }
    int exit_test = argc == 4 && !strcmp(argv[1], "control-exit");
    if (argc != 4 || (strcmp(argv[1], "control") && !exit_test)) return 2;
    pid_t pid = atoi(argv[2]);
    uint64_t entry = strtoull(argv[3], NULL, 0);
    uint64_t memory = allocate(pid, 4096), stack = allocate(pid, 65536);
    struct report report = {0};
    int ok = 0, spawned = 0;
    long tid = -1;
    if (!memory || !stack) goto cleanup;
    uint64_t pattern = UINT64_C(0x1248abcdef678901), readback = 0;
    if (transfer(pid, memory + 128, &pattern, sizeof(pattern), 1) ||
        transfer(pid, memory + 128, &readback, sizeof(readback), 0) || readback != pattern)
        goto cleanup;
    struct spawn_args args = {entry, stack + 65536 - 16, memory, memory + 2048, (uint32_t)pid};
    if (exit_test) {
        /* Exit after allocations and transfers, but before thread setup. The
         * process teardown owns the mappings; do not free a reused PID's mm. */
        if (kill(pid, SIGTERM)) return 1;
        char target_path[64];
        snprintf(target_path, sizeof(target_path), "/proc/%d", pid);
        for (int i = 0; i != 300 && access(target_path, F_OK) == 0; i++) usleep(10000);
        if (access(target_path, F_OK) == 0) return 1;
        errno = 0;
        tid = control(68, &args);
        printf("{\"stage\":\"target-exit\",\"ok\":%s,\"tid\":%ld,\"errno\":%d}\n",
               tid == -1 && errno == ESRCH ? "true" : "false", tid, errno);
        return tid == -1 && errno == ESRCH ? 0 : 1;
    }
    tid = control(68, &args);
    if (tid <= 0) goto cleanup;
    spawned = 1;
    for (int i = 0; i != 300; i++) {
        if (transfer(pid, memory, &report, sizeof(report), 0)) break;
        if (report.done) break;
        usleep(10000);
    }
    printf("{\"stage\":\"thread\",\"target\":%d,\"returned_tid\":%ld,\"pid\":%" PRIu64
           ",\"tid\":%" PRIu64 ",\"uid\":%" PRIu64 ",\"tls\":\"0x%" PRIx64
           "\",\"expected_tls\":\"0x%" PRIx64 "\",\"done\":%" PRIu64 "}\n",
           pid, tid, report.pid, report.tid, report.uid, report.tls, args.tls, report.done);
    fflush(stdout);
    ok = report.done && report.pid == (uint64_t)pid && report.tid == (uint64_t)tid && report.tls == args.tls;
    /* Give the host time to inspect /proc/PID/task/TID/status. */
    sleep(2);
    uint64_t one = 1;
    if (transfer(pid, memory + 40, &one, sizeof(one), 1)) ok = 0;
    char path[128];
    snprintf(path, sizeof(path), "/proc/%d/task/%ld", pid, tid);
    for (int i = 0; i != 300 && access(path, F_OK) == 0; i++) usleep(10000);
    if (access(path, F_OK) == 0) {
        fprintf(stderr, "thread still present; leaving mappings for inspection\n");
        return 1;
    }
    spawned = 0;
cleanup:
    if (!spawned) {
        if (stack && release(pid, stack, 65536)) ok = 0;
        if (memory && release(pid, memory, 4096)) ok = 0;
    }
    printf("{\"stage\":\"complete\",\"ok\":%s,\"tid\":%ld,\"errno\":%d}\n", ok ? "true" : "false", tid, errno);
    return ok ? 0 : 1;
}
