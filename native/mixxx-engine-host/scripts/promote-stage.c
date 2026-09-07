#include <errno.h>
#include <stdio.h>
#include <sys/stat.h>
#include <sys/stdio.h>

// Called only with exact paths beneath the script's generated stage directory.
// Refuse symlinks and non-directories; an old bundle survives the atomic swap.
int main(int argc, char** argv) {
    if (argc != 3) return 2;
    struct stat source, destination;
    if (lstat(argv[1], &source) != 0 || !S_ISDIR(source.st_mode)) return 2;
    int result;
    if (lstat(argv[2], &destination) == 0) {
        if (!S_ISDIR(destination.st_mode)) return 2;
        result = renamex_np(argv[1], argv[2], RENAME_SWAP);
    } else {
        if (errno != ENOENT) return 2;
        result = rename(argv[1], argv[2]);
    }
    if (result != 0) { perror("Cannot atomically promote staged bundle"); return 1; }
    return 0;
}
