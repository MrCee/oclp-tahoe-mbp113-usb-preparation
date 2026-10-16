/* Minimal x86_64 macOS helper for Recovery: no Perl/Python or plutil dependency.
 * Only reads property lists/files and calculates SHA-256. No disk writes.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <CommonCrypto/CommonDigest.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/mount.h>

static CFPropertyListRef load_plist(const char *name) {
    FILE *f = strcmp(name, "-") == 0 ? stdin : fopen(name, "rb");
    if (!f) { perror(name); return NULL; }
    CFMutableDataRef data = CFDataCreateMutable(NULL, 0);
    unsigned char buf[65536]; size_t n; int bad = 0;
    while ((n = fread(buf, 1, sizeof(buf), f))) {
        if (CFDataGetLength(data) + (CFIndex)n > 16 * 1024 * 1024) { bad = 1; break; }
        CFDataAppendBytes(data, buf, (CFIndex)n);
    }
    if (ferror(f)) bad = 1;
    if (f != stdin) fclose(f);
    CFPropertyListRef result = NULL;
    if (!bad) result = CFPropertyListCreateWithData(NULL, data, kCFPropertyListImmutable, NULL, NULL);
    CFRelease(data);
    if (!result) fprintf(stderr, "Cannot parse plist: %s\n", name);
    return result;
}

static int plist_value(const char *name, const char *path) {
    CFPropertyListRef plist = load_plist(name); if (!plist) return 1;
    CFTypeRef node = plist; char *keys = strdup(path), *save = NULL;
    if (!keys) { CFRelease(plist); return 1; }
    for (char *key = strtok_r(keys, ".", &save); key && node; key = strtok_r(NULL, ".", &save)) {
        if (CFGetTypeID(node) == CFDictionaryGetTypeID()) {
            CFStringRef k = CFStringCreateWithCString(NULL, key, kCFStringEncodingUTF8);
            node = k ? CFDictionaryGetValue(node, k) : NULL;
            if (k) CFRelease(k);
        } else if (CFGetTypeID(node) == CFArrayGetTypeID()) {
            char *end; long i = strtol(key, &end, 10);
            if (*end || !*key || i < 0 || i >= CFArrayGetCount(node)) node = NULL;
            else node = CFArrayGetValueAtIndex(node, i);
        } else node = NULL;
    }
    free(keys); int status = 1;
    if (node && CFGetTypeID(node) == CFStringGetTypeID()) {
        CFIndex cap = CFStringGetMaximumSizeForEncoding(CFStringGetLength(node), kCFStringEncodingUTF8) + 1;
        char *s = malloc((size_t)cap);
        if (s && CFStringGetCString(node, s, cap, kCFStringEncodingUTF8)) { puts(s); status = 0; }
        free(s);
    } else if (node && CFGetTypeID(node) == CFBooleanGetTypeID()) {
        puts(CFBooleanGetValue(node) ? "true" : "false"); status = 0;
    } else if (node && CFGetTypeID(node) == CFNumberGetTypeID()) {
        long long i; if (CFNumberGetValue(node, kCFNumberLongLongType, &i)) { printf("%lld\n", i); status = 0; }
    }
    CFRelease(plist); return status;
}

static int sha(const char *name, char out[65]) {
    FILE *f = fopen(name, "rb"); if (!f) { perror(name); return 1; }
    CC_SHA256_CTX ctx; CC_SHA256_Init(&ctx);
    unsigned char buf[65536], digest[CC_SHA256_DIGEST_LENGTH]; size_t n;
    while ((n = fread(buf, 1, sizeof(buf), f))) CC_SHA256_Update(&ctx, buf, (CC_LONG)n);
    int bad = ferror(f); fclose(f); if (bad) { fprintf(stderr, "Read failed: %s\n", name); return 1; }
    CC_SHA256_Final(digest, &ctx);
    for (int i = 0; i < CC_SHA256_DIGEST_LENGTH; ++i) sprintf(out + i * 2, "%02x", digest[i]);
    return 0;
}

static int sha_check(const char *name) {
    FILE *f = fopen(name, "r"); if (!f) { perror(name); return 1; }
    char *line = NULL; size_t cap = 0; ssize_t n; int bad = 0, count = 0;
    while ((n = getline(&line, &cap, f)) >= 0) {
        if (n && line[n - 1] == '\n') line[--n] = 0;
        if (n < 67 || line[64] != ' ' || line[65] != ' ') { bad = 1; break; }
        char *file = line + 66;
        if (*file == '/' || strcmp(file, "..") == 0 || strncmp(file, "../", 3) == 0 || strstr(file, "/../") || (strlen(file) >= 3 && strcmp(file + strlen(file) - 3, "/..") == 0)) { bad = 1; break; }
        for (int i = 0; i < 64; i++) if (!((line[i] >= '0' && line[i] <= '9') || (line[i] >= 'a' && line[i] <= 'f'))) { bad = 1; break; }
        if (bad) break;
        char actual[65]; int ok = sha(file, actual) == 0 && strncmp(line, actual, 64) == 0;
        printf("%s: %s\n", file, ok ? "OK" : "FAILED"); fflush(stdout);
        if (!ok) bad = 1;
        count++;
    }
    if (ferror(f)) bad = 1;
    free(line); fclose(f);
    if (!count) bad = 1;
    return bad;
}

int main(int argc, char **argv) {
    if (argc == 3 && strcmp(argv[1], "free-kb") == 0) { struct statfs s; if (statfs(argv[2], &s) != 0) { perror(argv[2]); return 1; } printf("%llu\n", (unsigned long long)s.f_bavail * s.f_bsize / 1024); return 0; }
    if (argc == 4 && strcmp(argv[1], "value") == 0) return plist_value(argv[2], argv[3]);
    if (argc == 3 && strcmp(argv[1], "lint") == 0) { CFPropertyListRef p = load_plist(argv[2]); if (!p) return 1; CFRelease(p); printf("%s: OK\n", argv[2]); return 0; }
    if (argc == 3 && strcmp(argv[1], "sha256") == 0) { char out[65]; if (sha(argv[2], out)) return 1; puts(out); return 0; }
    if (argc == 3 && strcmp(argv[1], "sha-check") == 0) return sha_check(argv[2]);
    fprintf(stderr, "Usage: recovery-tool value FILE KEY.PATH | lint FILE | sha256 FILE | sha-check MANIFEST | free-kb PATH\n"); return 2;
}
