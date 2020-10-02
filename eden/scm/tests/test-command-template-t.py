import sys
is_py3 = sys.version_info[0] >= 3
with open("second", "wb") as f:
    # Valid utf-8 character
    if is_py3:
        f.write("🥈".encode("utf-8"))
    else:
        f.write("🥈")
    # Invalid utf-8 character
    f.write(b"\xe2\x28\xa1")
    f.write(b"\n")
     {"node": "209edb6a1848", "rev": 8},
     {"node": "88058a185da2", "rev": 7}
     {"node": "209edb6a1848", "rev": 8},
     {"node": "88058a185da2", "rev": 7}
    209edb6a1848   2020-01-01 10:01 +0000   test
       88058a185da2   1970-01-12 13:46 +0000   user
    209edb6a1848   2020-01-01 10:01 +0000   test
    88058a185da2   1970-01-12 13:46 +0000   User Name <user@hostname>
    209edb6a1848   2020-01-01 10:01 +0000   test
    88058a185da2   1970-01-12 13:46 +0000   User Name <user@hostname>
    <logentry node="209edb6a18483c1434e4006bca4c2b1ee5e7090a">
    <logentry node="88058a185da202d22e8ee0bb4d3515ff0ecb222b">
    <logentry node="209edb6a18483c1434e4006bca4c2b1ee5e7090a">
    <logentry node="88058a185da202d22e8ee0bb4d3515ff0ecb222b">
    <logentry node="209edb6a18483c1434e4006bca4c2b1ee5e7090a">
    <logentry node="88058a185da202d22e8ee0bb4d3515ff0ecb222b">
      "node": "209edb6a18483c1434e4006bca4c2b1ee5e7090a"
sh % "hg log -vpr . -Tjson --stat" == (
    r"""
      "node": "209edb6a18483c1434e4006bca4c2b1ee5e7090a",
      "parents": ["88058a185da202d22e8ee0bb4d3515ff0ecb222b"],
      "diffstat": " fourth |  1 +\n second |  1 -\n third  |  1 +\n 3 files changed, 2 insertions(+), 1 deletions(-)\n",""" +
(
    '\n      "diff": "diff -r 88058a185da2 -r 209edb6a1848 fourth\\n--- /dev/null\\tThu Jan 01 00:00:00 1970 +0000\\n+++ b/fourth\\tWed Jan 01 10:01:00 2020 +0000\\n@@ -0,0 +1,1 @@\\n+🥈\udced\udcb3\udca2(\udced\udcb2\udca1\\ndiff -r 88058a185da2 -r 209edb6a1848 second\\n--- a/second\\tMon Jan 12 13:46:40 1970 +0000\\n+++ /dev/null\\tThu Jan 01 00:00:00 1970 +0000\\n@@ -1,1 +0,0 @@\\n-🥈\udced\udcb3\udca2(\udced\udcb2\udca1\\ndiff -r 88058a185da2 -r 209edb6a1848 third\\n--- /dev/null\\tThu Jan 01 00:00:00 1970 +0000\\n+++ b/third\\tWed Jan 01 10:01:00 2020 +0000\\n@@ -0,0 +1,1 @@\\n+third\\n"\n'
if is_py3 else
    '\n      "diff": "diff -r 88058a185da2 -r 209edb6a1848 fourth\\n--- /dev/null\\tThu Jan 01 00:00:00 1970 +0000\\n+++ b/fourth\\tWed Jan 01 10:01:00 2020 +0000\\n@@ -0,0 +1,1 @@\\n+🥈\xed\xb3\xa2(\xed\xb2\xa1\\ndiff -r 88058a185da2 -r 209edb6a1848 second\\n--- a/second\\tMon Jan 12 13:46:40 1970 +0000\\n+++ /dev/null\\tThu Jan 01 00:00:00 1970 +0000\\n@@ -1,1 +0,0 @@\\n-🥈\xed\xb3\xa2(\xed\xb2\xa1\\ndiff -r 88058a185da2 -r 209edb6a1848 third\\n--- /dev/null\\tThu Jan 01 00:00:00 1970 +0000\\n+++ b/third\\tWed Jan 01 10:01:00 2020 +0000\\n@@ -0,0 +1,1 @@\\n+third\\n"\n'
) +
    r"""     }
)
      "node": "209edb6a18483c1434e4006bca4c2b1ee5e7090a",
      "parents": ["88058a185da202d22e8ee0bb4d3515ff0ecb222b"],
      "node": "209edb6a18483c1434e4006bca4c2b1ee5e7090a",
      "parents": ["88058a185da202d22e8ee0bb4d3515ff0ecb222b"]
      "node": "88058a185da202d22e8ee0bb4d3515ff0ecb222b",
      "node": "209edb6a18483c1434e4006bca4c2b1ee5e7090a",
      "parents": ["88058a185da202d22e8ee0bb4d3515ff0ecb222b"],
      "node": "209edb6a18483c1434e4006bca4c2b1ee5e7090a",
      "parents": ["88058a185da202d22e8ee0bb4d3515ff0ecb222b"],
      "manifest": "102f85d6546830d0894e5420cdddaa12fe270c02",
      "node": "88058a185da202d22e8ee0bb4d3515ff0ecb222b",
      "manifest": "e3aa144e25d914ea34006bd7b3c266b7eb283c61",
     [209edb6a1848]
     [88058a185da2]
     [209edb6a1848]
    manifest: 102f85d65468
    manifest: e3aa144e25d9
    manifest--verbose: 102f85d65468
    manifest--verbose: e3aa144e25d9
    manifest--debug: 102f85d6546830d0894e5420cdddaa12fe270c02
    manifest--debug: e3aa144e25d914ea34006bd7b3c266b7eb283c61
    node: 209edb6a18483c1434e4006bca4c2b1ee5e7090a
    node: 88058a185da202d22e8ee0bb4d3515ff0ecb222b
    node--verbose: 209edb6a18483c1434e4006bca4c2b1ee5e7090a
    node--verbose: 88058a185da202d22e8ee0bb4d3515ff0ecb222b
    node--debug: 209edb6a18483c1434e4006bca4c2b1ee5e7090a
    node--debug: 88058a185da202d22e8ee0bb4d3515ff0ecb222b
    parents: 88058a185da2
    parents--verbose: 88058a185da2
    parents--debug: 88058a185da202d22e8ee0bb4d3515ff0ecb222b
    p1node: 88058a185da202d22e8ee0bb4d3515ff0ecb222b
    p1node--verbose: 88058a185da202d22e8ee0bb4d3515ff0ecb222b
    p1node--debug: 88058a185da202d22e8ee0bb4d3515ff0ecb222b
    209edb6a1848
    88058a185da2
    7: 8:209edb6a1848
    commit:      bc9dfec3b3bc
    commit:      bc9dfec3b3bc
    commit:      bc9dfec3b3bc
    commit:      bc9dfec3b3bcc43c41a22000f3226b0c1085d5c1
    manifest:    1685af69a14aa2346cfb01cf0e7f50ef176128b4
sh % "hg log -T status -C -r 10 --quiet" == "bc9dfec3b3bc"
    [log.changeset changeset.draft|commit:      bc9dfec3b3bc]
    [log.changeset changeset.draft|commit:      bc9dfec3b3bc]
    [log.changeset changeset.draft|commit:      bc9dfec3b3bc]
    [log.changeset changeset.draft|commit:      bc9dfec3b3bcc43c41a22000f3226b0c1085d5c1]
    [ui.debug log.manifest|manifest:    1685af69a14aa2346cfb01cf0e7f50ef176128b4]
sh % "hg '--color=debug' log -T status -C -r 10 --quiet" == "[log.node|bc9dfec3b3bc]"
sh % "hg diff -c 8" == (
    r"""
    diff -r 88058a185da2 -r 209edb6a1848 fourth
"""
+ ("    +🥈\udce2(\udca1" if is_py3 else "    +🥈\xe2\x28\xa1") +
    """
    diff -r 88058a185da2 -r 209edb6a1848 second
"""
+ ("    -🥈\udce2(\udca1" if is_py3 else "    -🥈\xe2\x28\xa1") +
    """
    diff -r 88058a185da2 -r 209edb6a1848 third
)
sh % "hg log -r 8 -T '{diff()}'" == (
    r"""
    diff -r 88058a185da2 -r 209edb6a1848 fourth
"""
+ ("    +🥈\udce2(\udca1" if is_py3 else "    +🥈\xe2\x28\xa1") +
    """
    diff -r 88058a185da2 -r 209edb6a1848 second
"""
+ ("    -🥈\udce2(\udca1" if is_py3 else "    -🥈\xe2\x28\xa1") +
    """
    diff -r 88058a185da2 -r 209edb6a1848 third
)
sh % "hg log -r 8 -T '{diff('\\''glob:f*'\\'')}'" == (
    r"""
    diff -r 88058a185da2 -r 209edb6a1848 fourth
"""
+ ("    +🥈\udce2(\udca1" if is_py3 else "    +🥈\xe2\x28\xa1")
)
sh % "hg log -r 8 -T '{diff('\\'''\\'', '\\''glob:f*'\\'')}'" == (
    r"""
    diff -r 88058a185da2 -r 209edb6a1848 second
"""
+ ("    -🥈\udce2(\udca1" if is_py3 else "    -🥈\xe2\x28\xa1") +
    """
    diff -r 88058a185da2 -r 209edb6a1848 third
)
sh % "hg log -r 8 -T '{diff('\\''FOURTH'\\''|lower)}'" == (
    r"""
    diff -r 88058a185da2 -r 209edb6a1848 fourth
"""
+ ("    +🥈\udce2(\udca1" if is_py3 else "    +🥈\xe2\x28\xa1")
)
sh % 'hg log -R a -r 8 -T \'{"{"{rev}:{node|short}"}"}\\n\'' == "8:209edb6a1848"
sh % 'hg log -R a -r 8 -T \'{"{"\\{{rev}} \\"{node|short}\\""}"}\\n\'' == '{8} "209edb6a1848"'