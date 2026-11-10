/* Kill a disposable App at a traced injection stage, using a pidfd so PID
 * reuse cannot redirect the signal. Requires root and trace_process_ops=1.
 * Build with an Android arm64 NDK compiler. Does not change the module.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

static uint64_t now_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) abort();
    return (uint64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: exit-on-injection PID PACKAGE alloc|write|spawn|thread-ready\n");
        return 2;
    }
    char *end;
    long parsed = strtol(argv[1], &end, 10);
    if (*end || parsed <= 1 || parsed > 2147483647) return 2;
    int pid = (int)parsed;
    const char *stage = argv[3];
    if (strcmp(stage, "alloc") && strcmp(stage, "write") &&
        strcmp(stage, "spawn") && strcmp(stage, "thread-ready")) return 2;

    int target = syscall(SYS_pidfd_open, pid, 0);
    if (target < 0) { perror("pidfd_open"); return 1; }
    char path[64], name[4096];
    snprintf(path, sizeof(path), "/proc/%d/cmdline", pid);
    int cmdline = open(path, O_RDONLY | O_CLOEXEC);
    if (cmdline < 0) { perror("cmdline"); return 1; }
    ssize_t n = read(cmdline, name, sizeof(name) - 1);
    close(cmdline);
    if (n <= 0) return 1;
    name[n] = 0;
    if (strcmp(name, argv[2])) {
        fprintf(stderr, "target package does not match PID\n");
        return 1;
    }
    int log = open("/dev/kmsg", O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (log < 0) { perror("kmsg"); return 1; }
    if (lseek(log, 0, SEEK_END) < 0) { perror("kmsg seek"); return 1; }
    int marker = open("/dev/kmsg", O_WRONLY | O_CLOEXEC);
    if (marker < 0) { perror("kmsg marker"); return 1; }
    char match[128];
    snprintf(match, sizeof(match), "frida: process op=%s pid=%d %s", stage, pid,
             strcmp(stage, "thread-ready") == 0 ? "tid=" : "received");
    setvbuf(stdout, NULL, _IONBF, 0);
    printf("{\"kind\":\"ready\",\"pid\":%d,\"stage\":\"%s\"}\n", pid, stage);
    uint64_t deadline = now_ns() + 10000000000ULL;
    struct pollfd fds[2] = {{log, POLLIN, 0}, {target, POLLIN, 0}};
    while (now_ns() < deadline) {
        int r = poll(fds, 2, 100);
        if (r < 0 && errno == EINTR) continue;
        if (r < 0) { perror("poll"); return 1; }
        if (fds[0].revents & POLLIN) {
            char record[16384];
            while ((n = read(log, record, sizeof(record) - 1)) > 0) {
                record[n] = 0;
                if (!strstr(record, match)) continue;
                unsigned priority;
                uint64_t sequence, timestamp;
                if (sscanf(record, "%u,%" SCNu64 ",%" SCNu64 ",",
                           &priority, &sequence, &timestamp) != 3) return 1;
                if (dprintf(marker, "frida-race: kill-request pid=%d stage=%s\n", pid, stage) < 0) return 1;
                uint64_t before = now_ns();
                int result = syscall(SYS_pidfd_send_signal, target, SIGKILL, NULL, 0);
                int saved_errno = result == 0 ? 0 : errno;
                uint64_t after = now_ns();
                if (dprintf(marker, "frida-race: kill-sent pid=%d stage=%s result=%d\n", pid, stage, result) < 0)
                    return 1;
                printf("{\"kind\":\"kill\",\"pid\":%d,\"stage\":\"%s\","
                       "\"kernel_sequence\":%" PRIu64 ",\"kernel_time_us\":%" PRIu64 ","
                       "\"before_ns\":%" PRIu64 ",\"after_ns\":%" PRIu64 ","
                       "\"result\":%d,\"errno\":%d}\n",
                       pid, stage, sequence, timestamp, before, after, result, saved_errno);
                if (result) return 1;
                struct pollfd exited = {target, POLLIN, 0};
                r = poll(&exited, 1, 5000);
                int gone = r > 0 && (exited.revents & POLLIN);
                printf("{\"kind\":\"exit\",\"pid\":%d,\"exited\":%s,"
                       "\"time_ns\":%" PRIu64 "}\n", pid, gone ? "true" : "false", now_ns());
                close(log);
                close(marker);
                close(target);
                return gone ? 0 : 1;
            }
            if (n < 0 && errno != EAGAIN) { perror("kmsg read"); return 1; }
        }
        if (fds[1].revents & POLLIN) {
            fprintf(stderr, "target exited before the selected injection event\n");
            return 1;
        }
    }
    fprintf(stderr, "timed out waiting for the injection event\n");
    return 1;
}
