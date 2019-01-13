README
======

Evaluation
===

To re-run evaluation, execute the following commands:

```
cd ~/eval
./eval.py
```

The process should run for 4-6 hours. 

```mkcheck``` must be build before evaluation:

```
cd `~/mkcheck/build
cmake ..
make
```

eval.py
===

Evaluation is performed by the ```eval.py``` script in the eval directory.
The process is fully automated: the script downloads and builds all projects,
producing a report. The columns of the report are:

* name of the poject
* number of files tested
* number of files which trigger stale builds
* number of files which trigger redundant builds
* flag indicating whether races were detected
* flag indicating whether the project was fixed

Detailed information is available in the eval/tmp/output folder, in the following files:

* ```eval/tmp/output/[project]/build-[orig|fixed].log``` contains build logs if a build fails

* ```eval/tmp/output/[project]/graph-[orig|fixed]``` contains the JSON dependency graph

* ```eval/tmp/output/[project]/fuzz-[orig|fixed].log``` contains the fuzzing log

* ```eval/tmp/output/[project]/race-[orig|fixed].log``` contains the race detection log

Filed with the ```orig``` suffix are generated while testing the unmodified project, 
while files with the ```fixed``` suffix are generated by the fixed projects.

The script performs the following actions, for each project:

* downloads the project into the ```src-orig``` directory
* if necessary, applies a patch to fix the build
* if necessary, performs a configuration step
* builds the project, generating the graph
* fuzzes the project
* performs race condition detection

If a fix is provided in the ```patches``` directory under ```patches/[project]-fixed.diff```,
the steps are repeated, but the project is downloaded to the ```src-fixed``` directory.

Projects might have blacklist files which exclude files from fuzzing to
reduce evaluation times. These are located in the ```rules``` directory.


