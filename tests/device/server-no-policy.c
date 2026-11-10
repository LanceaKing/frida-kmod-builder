/* Run the unchanged official server with policy reads blocked in a private
 * mount namespace. This makes frida_selinux_patch_policy return before writes.
 */
#define _GNU_SOURCE
#include <sched.h>
#include <stdio.h>
#include <sys/mount.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    if (unshare(CLONE_NEWNS) || mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL) ||
        mount("/dev/null", "/sys/fs/selinux/policy", NULL, MS_BIND, NULL)) {
        perror("private policy view");
        return 1;
    }
    execv(argv[1], argv + 1);
    perror("execv");
    return 1;
}
