#!/usr/bin/groovy
/* Copyright (C) 2019-2020 Intel Corporation
 * All rights reserved.
 *
 * This file is part of the DAOS Project. It is subject to the license terms
 * in the LICENSE file found in the top-level directory of this distribution
 * and at https://img.shields.io/badge/License-Apache%202.0-blue.svg.
 * No part of the DAOS Project, including this file, may be copied, modified,
 * propagated, or distributed except according to the terms contained in the
 * LICENSE file.
 */

// To use a test branch (i.e. PR) until it lands to master
// I.e. for testing library changes
@Library(value="pipeline-lib@bmurrell/build-leap-on-15.2-and-ubuntu-20.04") _

commit_pragma_cache = [:]

// Don't define this as a type or it loses it's global scope
target_branch = env.CHANGE_TARGET ? env.CHANGE_TARGET : env.BRANCH_NAME
def sanitized_JOB_NAME = JOB_NAME.toLowerCase().replaceAll('/', '-').replaceAll('%2f', '-')

// bail out of branch builds that are not on a whitelist
if (!env.CHANGE_ID &&
    (!env.BRANCH_NAME.startsWith("weekly-testing") &&
     !env.BRANCH_NAME.startsWith("release/") &&
     env.BRANCH_NAME != "master")) {
   currentBuild.result = 'SUCCESS'
   return
}

// The docker agent setup and the provisionNodes step need to know the
// UID that the build agent is running under.
cached_uid = 0
def getuid() {
    if (cached_uid == 0)
        cached_uid = sh(label: 'getuid()',
                        script: "id -u",
                        returnStdout: true).trim()
    return cached_uid
}

pipeline {
    agent { label 'lightweight' }

    triggers {
        cron(env.BRANCH_NAME == 'master' ? '0 0 * * *\n' : '' +
             env.BRANCH_NAME == 'weekly-testing' ? 'H 0 * * 6' : '')
    }

    environment {
        BULLSEYE = credentials('bullseye_license_key')
        GITHUB_USER = credentials('daos-jenkins-review-posting')
        SSH_KEY_ARGS = "-ici_key"
        CLUSH_ARGS = "-o$SSH_KEY_ARGS"
        QUICKBUILD_DEPS_EL7 = sh label:'Get Quickbuild dependencies',
                                 script: "rpmspec -q --define dist\\ .el7 " +
                                         "--undefine suse_version " +
                                         "--define rhel\\ 7 --srpm " +
                                         "--requires utils/rpms/daos.spec " +
                                         "2>/dev/null",
                                 returnStdout: true
        QUICKBUILD_DEPS_LEAP15 = sh label:'Get Quickbuild dependencies',
                                    script: "rpmspec -q --define dist\\ .suse.lp151 " +
                                            "--undefine rhel " +
                                            "--define suse_version\\ 1501 --srpm " +
                                            "--requires utils/rpms/daos.spec " +
                                            "2>/dev/null",
                                    returnStdout: true
        TEST_RPMS = cachedCommitPragma(pragma: 'RPM-test', def_val: 'true', cache: commit_pragma_cache)
    }

    options {
        // preserve stashes so that jobs can be started at the test stage
        preserveStashes(buildCount: 5)
        ansiColor('xterm')
    }

    stages {
        stage('Cancel Previous Builds') {
            when { changeRequest() }
            steps {
                cancelPreviousBuilds()
            }
        }
        stage('Pre-build') {
            when {
                beforeAgent true
                allOf {
                    not { branch 'weekly-testing' }
                    not { environment name: 'CHANGE_TARGET', value: 'weekly-testing' }
                }
            }
            parallel {
                stage('checkpatch') {
                    when {
                        beforeAgent true
                        allOf {
                            expression { ! skipStage(stage: 'checkpatch', cache: commit_pragma_cache) }
                            expression { ! docOnlyChange(target_branch) }
                        }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.centos.7'
                            dir 'utils/docker'
                            label 'docker_runner'
                            additionalBuildArgs dockerBuildArgs() +
                                           " -t ${sanitized_JOB_NAME}-centos7 "
                        }
                    }
                    steps {
                        checkPatch user: GITHUB_USER_USR,
                                   password: GITHUB_USER_PSW,
                                   ignored_files: "src/control/vendor/*:src/include/daos/*.pb-c.h:src/common/*.pb-c.[ch]:src/mgmt/*.pb-c.[ch]:src/iosrv/*.pb-c.[ch]:src/security/*.pb-c.[ch]:*.crt:*.pem:*_test.go:src/cart/_structures_from_macros_.h"
                    }
                    post {
                        always {
                            archiveArtifacts artifacts: 'pylint.log', allowEmptyArchive: true
                            /* when JENKINS-39203 is resolved, can probably use stepResult
                               here and remove the remaining post conditions
                               stepResult name: env.STAGE_NAME,
                                          context: 'build/' + env.STAGE_NAME,
                                          result: ${currentBuild.currentResult}
                            */
                        }
                        /* temporarily moved into stepResult due to JENKINS-39203
                        success {
                            githubNotify credentialsId: 'daos-jenkins-commit-status',
                                         description: env.STAGE_NAME,
                                         context: 'pre-build/' + env.STAGE_NAME,
                                         status: 'SUCCESS'
                        }
                        unstable {
                            githubNotify credentialsId: 'daos-jenkins-commit-status',
                                         description: env.STAGE_NAME,
                                         context: 'pre-build/' + env.STAGE_NAME,
                                         status: 'FAILURE'
                        }
                        failure {
                            githubNotify credentialsId: 'daos-jenkins-commit-status',
                                         description: env.STAGE_NAME,
                                         context: 'pre-build/' + env.STAGE_NAME,
                                         status: 'ERROR'
                        }
                        */
                    }
                } // stage('checkpatch')
                stage('Python Bandit check') {
                    when {
                      beforeAgent true
                      expression {
                          cachedCommitPragma(pragma: 'Skip-python-bandit',
                                             def_val: 'true',
                                             cache: commit_pragma_cache) != 'true'
                      }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.code_scanning'
                            dir 'utils/docker'
                            label 'docker_runner'
                            additionalBuildArgs dockerBuildArgs()
                        }
                    }
                    steps {
                        pythonBanditCheck()
                    }
                    post {
                        always {
                            // Bandit will have empty results if it does not
                            // find any issues.
                            junit testResults: 'bandit.xml',
                                  allowEmptyResults: true
                        }
                    }
                } // stage('Python Bandit check')
            }
        }
        stage('Build') {
            /* Don't use failFast here as whilst it avoids using extra resources
             * and gives faster results for PRs it's also on for master where we
             * do want complete results in the case of partial failure
             */
            //failFast true
            when {
                beforeAgent true
                anyOf {
                    // always build branch landings as we depend on lastSuccessfulBuild
                    // always having RPMs in it
                    branch target_branch
                    allOf {
                        expression { ! skipStage(stage: 'build', cache: commit_pragma_cache) }
                        expression { ! docOnlyChange(target_branch) }
                        expression { cachedCommitPragma(pragma: 'RPM-test-version', cache: commit_pragma_cache) == '' }
                    }
                }
            }
            parallel {
                stage('Build RPM on CentOS 7') {
                    agent {
                        dockerfile {
                            filename 'Dockerfile.mockbuild'
                            dir 'utils/rpms/packaging'
                            label 'docker_runner'
                            additionalBuildArgs dockerBuildArgs()
                            args  '--group-add mock --cap-add=SYS_ADMIN --privileged=true'
                        }
                    }
                    steps {
                        buildRpm()
                    }
                    post {
                        success {
                            buildRpmPost condition: 'success'
                        }
                        unstable {
                            buildRpmPost condition: 'unstable'
                        }
                        failure {
                            buildRpmPost condition: 'failure'
                        }
                        unsuccessful {
                            buildRpmPost condition: 'unsuccessful'
                        }
                        cleanup {
                            buildRpmPost condition: 'cleanup'
                        }
                    }
                }
                stage('Build RPM on Leap 15') {
                    when {
                        beforeAgent true
                        allOf {
                            not { branch 'weekly-testing' }
                            not { environment name: 'CHANGE_TARGET',
                                              value: 'weekly-testing' }
                            expression { ! skip_stage('build-leap15-rpm') }
                        }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.mockbuild'
                            dir 'utils/rpms/packaging'
                            label 'docker_runner'
                            args '--privileged=true'
                            additionalBuildArgs '$BUILDARGS'
                            args  '--group-add mock --cap-add=SYS_ADMIN --privileged=true'
                        }
                    }
                    steps {
                        buildRpm unstable: true
                    }
                    post {
                        success {
                            buildRpmPost condition: 'success'
                        }
                        unstable {
                            buildRpmPost condition: 'unstable'
                        }
                        failure {
                            buildRpmPost condition: 'failure'
                        }
                        unsuccessful {
                            buildRpmPost condition: 'unsuccessful'
                        }
                        cleanup {
                            buildRpmPost condition: 'cleanup'
                        }
                    }
                }
                stage('Build DEB on Ubuntu 20.04') {
                    when {
                        beforeAgent true
                        allOf {
                            not { branch 'weekly-testing' }
                            not { environment name: 'CHANGE_TARGET',
                                              value: 'weekly-testing' }
                            expression { ! skipStage(stage: 'build-ubuntu.20.04') }
                        }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.ubuntu.20.04'
                            dir 'utils/rpms/packaging'
                            label 'docker_runner'
                            args '--privileged=true'
                            additionalBuildArgs dockerBuildArgs()
                            args  '--cap-add=SYS_ADMIN --privileged=true'
                        }
                    }
                    steps {
                        buildRpm unstable: true
                    }
                    post {
                        success {
                            buildRpmPost condition: 'success'
                        }
                        unstable {
                            buildRpmPost condition: 'unstable'
                        }
                        failure {
                            buildRpmPost condition: 'failure'
                        }
                        unsuccessful {
                            buildRpmPost condition: 'unsuccessful'
                        }
                        cleanup {
                            buildRpmPost condition: 'cleanup'
                        }
                    }
                }
                stage('Build on CentOS 7') {
                    when {
                        beforeAgent true
                        allOf {
                            expression { ! skipStage(stage: 'build-centos7-gcc', cache: commit_pragma_cache) }
                        }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.centos.7'
                            dir 'utils/docker'
                            label 'docker_runner'
                            additionalBuildArgs dockerBuildArgs(qb: quickBuild(commit_pragma_cache)) +
                                                " -t ${sanitized_JOB_NAME}-centos7 " +
                                                ' --build-arg QUICKBUILD_DEPS="' +
                                                  env.QUICKBUILD_DEPS_EL7 + '"' +
                                                ' --build-arg REPOS="' + prRepos(commit_pragma_cache) + '"'
                        }
                    }
                    steps {
                        sconsBuild parallelBuild: parallelBuild(commit_pragma_cache),
                                   stash_files: 'ci/test_files_to_stash.txt'
                    }
                    post {
                        always {
                            recordIssues enabledForFailure: true,
                                         aggregatingResults: true,
                                         id: "analysis-gcc-centos7",
                                         tools: [ gcc4(pattern: 'centos7-gcc-build.log'),
                                                  cppCheck(pattern: 'centos7-gcc-build.log') ],
                                         filters: [ excludeFile('.*\\/_build\\.external\\/.*'),
                                                    excludeFile('_build\\.external\\/.*') ]
                        }
                        success {
                            sh "rm -rf _build.external"
                        }
                        unsuccessful {
                            sh """if [ -f config.log ]; then
                                      mv config.log config.log-centos7-gcc
                                  fi"""
                            archiveArtifacts artifacts: 'config.log-centos7-gcc',
                                             allowEmptyArchive: true
                        }
                    }
                }
                stage('Build on CentOS 7 debug') {
                    when {
                        beforeAgent true
                        allOf {
                            expression { ! skipStage(stage: 'build-centos7-gcc-debug', cache: commit_pragma_cache) }
                            expression { ! quickBuild(commit_pragma_cache) }
                        }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.centos.7'
                            dir 'utils/docker'
                            label 'docker_runner'
                            additionalBuildArgs dockerBuildArgs(qb: quickBuild(commit_pragma_cache)) +
                                                " -t ${sanitized_JOB_NAME}-centos7 " +
                                                ' --build-arg QUICKBUILD_DEPS="' +
                                                  env.QUICKBUILD_DEPS_EL7 + '"' +
                                                ' --build-arg REPOS="' + prRepos(commit_pragma_cache) + '"'
                        }
                    }
                    steps {
                        sconsBuild parallelBuild: parallelBuild(commit_pragma_cache)
                    }
                    post {
                        always {
                            recordIssues enabledForFailure: true,
                                         aggregatingResults: true,
                                         id: "analysis-gcc-centos7-debug",
                                         tools: [ gcc4(pattern: 'centos7-gcc-debug-build.log'),
                                                  cppCheck(pattern: 'centos7-gcc-debug-build.log') ],
                                         filters: [ excludeFile('.*\\/_build\\.external\\/.*'),
                                                   excludeFile('_build\\.external\\/.*') ]
                        }
                        success {
                            sh "rm -rf _build.external"
                        }
                        unsuccessful {
                            sh """if [ -f config.log ]; then
                                      mv config.log config.log-centos7-gcc-debug
                                  fi"""
                            archiveArtifacts artifacts: 'config.log-centos7-gcc-debug',
                                             allowEmptyArchive: true
                        }
                    }
                }
                stage('Build on CentOS 7 release') {
                    when {
                        beforeAgent true
                        allOf {
                            expression { ! skipStage(stage: 'build-centos7-gcc-release', cache: commit_pragma_cache) }
                            expression { ! quickBuild(commit_pragma_cache) }
                        }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.centos.7'
                            dir 'utils/docker'
                            label 'docker_runner'
                            additionalBuildArgs dockerBuildArgs(qb: quickBuild(commit_pragma_cache)) +
                                                " -t ${sanitized_JOB_NAME}-centos7 " +
                                                ' --build-arg QUICKBUILD_DEPS="' +
                                                  env.QUICKBUILD_DEPS_EL7 + '"' +
                                                ' --build-arg REPOS="' + prRepos(commit_pragma_cache) + '"'
                        }
                    }
                    steps {
                        sconsBuild parallelBuild: parallelBuild(commit_pragma_cache)
                    }
                    post {
                        always {
                            recordIssues enabledForFailure: true,
                                         aggregatingResults: true,
                                         id: "analysis-gcc-centos7-release",
                                         tools: [ gcc4(pattern: 'centos7-gcc-release-build.log'),
                                                  cppCheck(pattern: 'centos7-gcc-release-build.log') ],
                                         filters: [excludeFile('.*\\/_build\\.external\\/.*'),
                                                   excludeFile('_build\\.external\\/.*')]
                        }
                        success {
                            sh "rm -rf _build.external"
                        }
                        unsuccessful {
                            sh """if [ -f config.log ]; then
                                      mv config.log config.log-centos7-gcc-release
                                  fi"""
                            archiveArtifacts artifacts: 'config.log-centos7-gcc-release',
                                             allowEmptyArchive: true
                        }
                    }
                }
                stage('Build on CentOS 7 with Clang') {
                    when {
                        beforeAgent true
                        allOf {
                            branch target_branch
                            expression { ! quickBuild(commit_pragma_cache) }
                        }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.centos.7'
                            dir 'utils/docker'
                            label 'docker_runner'
                            additionalBuildArgs dockerBuildArgs(qb: quickBuild(commit_pragma_cache)) +
                                                " -t ${sanitized_JOB_NAME}-centos7 " +
                                                ' --build-arg QUICKBUILD_DEPS="' +
                                                  env.QUICKBUILD_DEPS_EL7 + '"'
                        }
                    }
                    steps {
                        sconsBuild parallelBuild: parallelBuild(commit_pragma_cache)
                    }
                    post {
                        always {
                            recordIssues enabledForFailure: true,
                                         aggregatingResults: true,
                                         id: "analysis-centos7-clang",
                                         tools: [ clang(pattern: 'centos7-clang-build.log'),
                                                  cppCheck(pattern: 'centos7-clang-build.log') ],
                                         filters: [ excludeFile('.*\\/_build\\.external\\/.*'),
                                                    excludeFile('_build\\.external\\/.*') ]
                        }
                        success {
                            sh "rm -rf _build.external"
                        }
                        unsuccessful {
                            sh """if [ -f config.log ]; then
                                      mv config.log config.log-centos7-clang
                                  fi"""
                            archiveArtifacts artifacts: 'config.log-centos7-clang',
                                             allowEmptyArchive: true
                        }
                    }
                }
                stage('Build on Ubuntu 20.04') {
                    when {
                        beforeAgent true
                        allOf {
                            branch target_branch
                            expression { ! quickBuild(commit_pragma_cache) }
                        }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.ubuntu.20.04'
                            dir 'utils/docker'
                            label 'docker_runner'
                            additionalBuildArgs dockerBuildArgs() +
                                                " -t ${sanitized_JOB_NAME}-ubuntu20.04"
                        }
                    }
                    steps {
                        sconsBuild parallelBuild: parallelBuild(commit_pragma_cache)
                    }
                    post {
                        always {
                            recordIssues enabledForFailure: true,
                                         aggregatingResults: true,
                                         id: "analysis-ubuntu20",
                                         tools: [ gcc4(pattern: 'ubuntu20.04-gcc-build.log'),
                                                  cppCheck(pattern: 'ubuntu20.04-gcc-build.log') ],
                                         filters: [ excludeFile('.*\\/_build\\.external\\/.*'),
                                                    excludeFile('_build\\.external\\/.*') ]
                        }
                        success {
                            sh "rm -rf _build.external"
                        }
                        unsuccessful {
                            sh """if [ -f config.log ]; then
                                      mv config.log config.log-ubuntu20.04-gcc
                                  fi"""
                            archiveArtifacts artifacts: 'config.log-ubuntu20.04-gcc',
                                             allowEmptyArchive: true
                        }
                    }
                }
                stage('Build on Ubuntu 20.04 with Clang') {
                    when {
                        beforeAgent true
                        allOf {
                            not { branch 'weekly-testing' }
                            not { environment name: 'CHANGE_TARGET', value: 'weekly-testing' }
                            expression { ! quickBuild(commit_pragma_cache) }
                            expression { ! skipStage(stage: 'build-ubuntu-clang', cache: commit_pragma_cache) }
                        }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.ubuntu.20.04'
                            dir 'utils/docker'
                            label 'docker_runner'
                            additionalBuildArgs dockerBuildArgs() +
                                                " -t ${sanitized_JOB_NAME}-ubuntu20.04"
                        }
                    }
                    steps {
                        sconsBuild parallelBuild: parallelBuild(commit_pragma_cache)
                    }
                    post {
                        always {
                            recordIssues enabledForFailure: true,
                                         aggregatingResults: true,
                                         id: "analysis-ubuntu20-clang",
                                         tools: [ clang(pattern: 'ubuntu20.04-clang-build.log'),
                                                  cppCheck(pattern: 'ubuntu20.04-clang-build.log') ],
                                         filters: [ excludeFile('.*\\/_build\\.external\\/.*'),
                                                    excludeFile('_build\\.external\\/.*') ]
                        }
                        success {
                            sh "rm -rf _build.external"
                        }
                        unsuccessful {
                            sh """if [ -f config.log ]; then
                                      mv config.log config.log-ubuntu20.04-clang
                                  fi"""
                            archiveArtifacts artifacts: 'config.log-ubuntu20.04-clang',
                                             allowEmptyArchive: true
                        }
                    }
                }
                stage('Build on Leap 15') {
                    agent {
                        dockerfile {
                            filename 'Dockerfile.leap.15'
                            dir 'utils/docker'
                            label 'docker_runner'
                            additionalBuildArgs dockerBuildArgs(qb: quickBuild(commit_pragma_cache)) +
                                                " -t ${sanitized_JOB_NAME}-leap15 " +
                                                ' --build-arg QUICKBUILD_DEPS="' +
                                                  env.QUICKBUILD_DEPS_LEAP15 + '"' +
                                                ' --build-arg REPOS="' + prRepos(commit_pragma_cache) + '"'
                        }
                    }
                    steps {
                        sconsBuild parallelBuild: parallelBuild(commit_pragma_cache),
                                   stash_files: 'ci/test_files_to_stash.txt'
                    }
                    post {
                        always {
                            recordIssues enabledForFailure: true,
                                         aggregatingResults: true,
                                         id: "analysis-gcc-leap15",
                                         tools: [ gcc4(pattern: 'leap15-gcc-build.log'),
                                                  cppCheck(pattern: 'leap15-gcc-build.log') ],
                                         filters: [ excludeFile('.*\\/_build\\.external\\/.*'),
                                                    excludeFile('_build\\.external\\/.*') ]
                        }
                        success {
                            sh "rm -rf _build.external"
                        }
                        unsuccessful {
                            sh """if [ -f config.log ]; then
                                      mv config.log config.log-leap15-gcc
                                  fi"""
                            archiveArtifacts artifacts: 'config.log-leap15-gcc',
                                             allowEmptyArchive: true
                        }
                    }
                }
                stage('Build on Leap 15 with Clang') {
                    when {
                        beforeAgent true
                        allOf {
                            branch target_branch
                            expression { ! quickBuild(commit_pragma_cache) }
                        }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.leap.15'
                            dir 'utils/docker'
                            label 'docker_runner'
                            additionalBuildArgs dockerBuildArgs() +
                                                " -t ${sanitized_JOB_NAME}-leap15"
                        }
                    }
                    steps {
                        sconsBuild parallelBuild: parallelBuild(commit_pragma_cache)
                    }
                    post {
                        always {
                            recordIssues enabledForFailure: true,
                                         aggregatingResults: true,
                                         id: "analysis-leap15-clang",
                                         tools: [ clang(pattern: 'leap15-clang-build.log'),
                                                  cppCheck(pattern: 'leap15-clang-build.log') ],
                                         filters: [ excludeFile('.*\\/_build\\.external\\/.*'),
                                                    excludeFile('_build\\.external\\/.*') ]
                        }
                        success {
                            sh "rm -rf _build.external"
                        }
                        unsuccessful {
                            sh """if [ -f config.log ]; then
                                      mv config.log config.log-leap15-clang
                                  fi"""
                            archiveArtifacts artifacts: 'config.log-leap15-clang',
                                             allowEmptyArchive: true
                        }
                    }
                }
                stage('Build on Leap 15 with Intel-C and TARGET_PREFIX') {
                    when {
                        beforeAgent true
                        allOf {
                            not { branch 'weekly-testing' }
                            not { environment name: 'CHANGE_TARGET', value: 'weekly-testing' }
                            expression { ! quickBuild(commit_pragma_cache) }
                            expression { ! skipStage(stage: 'build-leap15-icc', cache: commit_pragma_cache) }
                        }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.leap.15'
                            dir 'utils/docker'
                            label 'docker_runner'
                            additionalBuildArgs dockerBuildArgs() +
                                                " -t ${sanitized_JOB_NAME}-leap15"
                            args '-v /opt/intel:/opt/intel'
                        }
                    }
                    steps {
                        sconsBuild parallelBuild: parallelBuild(commit_pragma_cache)
                    }
                    post {
                        always {
                            recordIssues enabledForFailure: true,
                                         aggregatingResults: true,
                                         id: "analysis-leap15-intelc",
                                         tools: [ intel(pattern: 'leap15-icc-build.log'),
                                                  cppCheck(pattern: 'leap15-icc-build.log') ],
                                         filters: [ excludeFile('.*\\/_build\\.external\\/.*'),
                                                    excludeFile('_build\\.external\\/.*') ]
                        }
                        success {
                            sh "rm -rf _build.external"
                        }
                        unsuccessful {
                            sh """if [ -f config.log ]; then
                                      mv config.log config.log-leap15-intelc
                                  fi"""
                            archiveArtifacts artifacts: 'config.log-leap15-intelc',
                                             allowEmptyArchive: true
                        }
                    }
                }
            }
        }
        stage('Unit Tests') {
            when {
                beforeAgent true
                allOf {
                    not { environment name: 'NO_CI_TESTING', value: 'true' }
                    // nothing to test if build was skipped
                    expression { ! skipStage(stage: 'build', cache: commit_pragma_cache) }
                    // or it's a doc-only change
                    expression { ! docOnlyChange(target_branch) }
                    expression { ! skipStage(stage: 'test', cache: commit_pragma_cache) }
                    expression { cachedCommitPragma(pragma: 'RPM-test-version', cache: commit_pragma_cache) == '' }
                }
            }
            parallel {
                stage('Unit Test') {
                    when {
                      beforeAgent true
                      allOf {
                          expression { ! skipStage(stage: 'unit-test', cache: commit_pragma_cache) }
                          expression { ! skipStage(stage: 'run_test', cache: commit_pragma_cache) }
                      }
                    }
                    agent {
                        label 'ci_vm1'
                    }
                    steps {
                        unitTest timeout_time: 60,
                                 inst_repos: prRepos(commit_pragma_cache),
                                 inst_rpms: unitPackages(commit_pragma_cache)
                    }
                    post {
                      always {
                            unitTestPost artifacts: ['unit_test_logs/*',
                                                     'unit_vm_test/**'],
                                         valgrind_stash: 'centos7-gcc-unit-valg'
                        }
                    }
                }
                stage('Unit Test Bullseye') {
                    when {
                      beforeAgent true
                      expression { ! skipStage(stage: 'bullseye',
                                               def_val: true,
                                               cache: commit_pragma_cache) }
                    }
                    agent {
                        label 'ci_vm1'
                    }
                    steps {
                        unitTest timeout_time: 60,
                                 ignore_failure: true,
                                 inst_repos: prRepos(commit_pragma_cache),
                                 inst_rpms: unitPackages(commit_pragma_cache)
                    }
                    post {
                        always {
                            // This is only set while dealing with issues
                            // caused by code coverage instrumentation affecting
                            // test results, and while code coverage is being
                            // added.
                            unitTestPost ignore_failure: true,
                                         artifacts: ['covc_test_logs/*',
                                                     'covc_vm_test/**']
                        }
                    }
                } // stage('Unit test Bullseye')
            }
        }
        stage('Test') {
            when {
                beforeAgent true
                allOf {
                    not { environment name: 'NO_CI_TESTING', value: 'true' }
                    // nothing to test if build was skipped
                    expression { ! skipStage(stage: 'build', cache: commit_pragma_cache) }
                    // or it's a doc-only change
                    expression { ! docOnlyChange(target_branch) }
                    expression { ! skipStage(stage: 'test', cache: commit_pragma_cache) }
                }
            }
            parallel {
                stage('Coverity on CentOS 7') {
                    when {
                        beforeAgent true
                        expression { ! skipStage(stage: 'coverity-test', cache: commit_pragma_cache) }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.centos.7'
                            dir 'utils/docker'
                            label 'docker_runner'
                            additionalBuildArgs dockerBuildArgs(qb: true) +
                                                " -t ${sanitized_JOB_NAME}-centos7 " +
                                                ' --build-arg QUICKBUILD_DEPS="' +
                                                  env.QUICKBUILD_DEPS_EL7 + '"' +
                                                ' --build-arg REPOS="' + prRepos(commit_pragma_cache) + '"'
                        }
                    }
                    steps {
                        sconsBuild coverity: "daos-stack/daos",
                                   parallelBuild: parallelBuild(commit_pragma_cache)
                    }
                    post {
                        success {
                            coverityPost condition: 'success'
                        }
                        unsuccessful {
                            coverityPost condition: 'unsuccessful'
                        }
                    }
                }
                stage('Functional on CentOS 7') {
                    when {
                        beforeAgent true
                        allOf {
                            expression { ! skipStage(stage: 'func-test', cache: commit_pragma_cache) }
                            expression { ! skipStage(stage: 'func-test-vm', cache: commit_pragma_cache) }
                            expression { ! skipStage(stage: 'func-test-el7', cache: commit_pragma_cache) }
                        }
                    }
                    agent {
                        label 'ci_vm9'
                    }
                    steps {
                        functionalTest inst_repos: daosRepos(commit_pragma_cache),
                                       inst_rpms: functionalPackages(commit_pragma_cache)
                    }
                    post {
                        always {
                            functionalTestPost()
                        }
                    }
                }
                stage('Functional on Leap 15') {
                    when {
                        beforeAgent true
                        allOf {
                            expression { ! skipStage(stage: 'func-test', cache: commit_pragma_cache) }
                            expression { ! skipStage(stage: 'func-test-vm', cache: commit_pragma_cache) }
                            expression { ! skipStage(stage: 'func-test-leap15', cache: commit_pragma_cache) }
                        }
                    }
                    agent {
                        label 'ci_vm9'
                    }
                    steps {
                        functionalTest inst_repos: daosRepos(commit_pragma_cache),
                                       inst_rpms: functionalPackages(commit_pragma_cache)
                    }
                    post {
                        always {
                            functionalTestPost()
                        }
                    } // post
                } // stage('Functional on Leap 15')
                stage('Functional on Ubuntu 20.04') {
                    when {
                        beforeAgent true
                        allOf {
                            expression { ! skipStage(stage: 'func-test', cache: commit_pragma_cache) }
                            expression { ! skipStage(stage: 'func-test-vm', cache: commit_pragma_cache) }
                            expression { ! skipStage(stage: 'func-test-ubumtu20', cache: commit_pragma_cache) }
                        }
                    }
                    agent {
                        label 'ci_vm9'
                    }
                    steps {
                        functionalTest inst_repos: daosRepos(commit_pragma_cache),
                                       inst_rpms: functionalPackages(commit_pragma_cache)
                    }
                    post {
                        always {
                            functionalTestPost()
                        }
                    } // post
                } // stage('Functional on Ubuntu 20.04') {
                stage('Functional_Hardware_Small') {
                    when {
                        beforeAgent true
                        allOf {
                            not { environment name: 'DAOS_STACK_CI_HARDWARE_SKIP', value: 'true' }
                            expression { ! skipStage(stage: 'func-hw-test', cache: commit_pragma_cache) }
                            expression { ! skipStage(stage: 'func-hw-test-small', cache: commit_pragma_cache) }
                        }
                    }
                    agent {
                        // 2 node cluster with 1 IB/node + 1 test control node
                        label 'stage_nvme3'
                    }
                    steps {
                        functionalTest target: hwDistroTarget(commit_pragma_cache),
                                       inst_repos: daosRepos(commit_pragma_cache),
                                       inst_rpms: functionalPackages(commit_pragma_cache)
                    }
                    post {
                        always {
                            functionalTestPost()
                        }
                    }
                } // stage('Functional_Hardware_Small')
                stage('Functional_Hardware_Medium') {
                    when {
                        beforeAgent true
                        allOf {
                            not { environment name: 'DAOS_STACK_CI_HARDWARE_SKIP', value: 'true' }
                            expression { ! skipStage(stage: 'func-hw-test', cache: commit_pragma_cache) }
                            expression { ! skipStage(stage: 'func-hw-test-medium', cache: commit_pragma_cache) }
                        }
                    }
                    agent {
                        // 4 node cluster with 2 IB/node + 1 test control node
                        label 'ci_nvme5'
                    }
                    steps {
                        functionalTest target: hwDistroTarget(commit_pragma_cache),
                                       inst_repos: daosRepos(commit_pragma_cache),
                                       inst_rpms: functionalPackages(commit_pragma_cache)
                   }
                    post {
                        always {
                            functionalTestPost()
                        }
                    }
                } // stage('Functional_Hardware_Medium')
                stage('Functional_Hardware_Large') {
                    when {
                        beforeAgent true
                        allOf {
                            not { environment name: 'DAOS_STACK_CI_HARDWARE_SKIP', value: 'true' }
                            expression { ! skipStage(stage: 'func-hw-test', cache: commit_pragma_cache) }
                            expression { ! skipStage(stage: 'func-hw-test-large', cache: commit_pragma_cache) }
                        }
                    }
                    agent {
                        // 8+ node cluster with 1 IB/node + 1 test control node
                        label 'ci_nvme9'
                    }
                    steps {
                        functionalTest target: hwDistroTarget(commit_pragma_cache),
                                       inst_repos: daosRepos(commit_pragma_cache),
                                       inst_rpms: functionalPackages(commit_pragma_cache)
                    }
                    post {
                        always {
                            functionalTestPost()
                        }
                    }
                } // stage('Functional_Hardware_Large')
                stage('Test CentOS 7 RPMs') {
                    when {
                        beforeAgent true
                        allOf {
                            not { branch 'weekly-testing' }
                            not { environment name: 'CHANGE_TARGET',
                                              value: 'weekly-testing' }
                            expression { ! skipStage(stage: 'test', cache: commit_pragma_cache) }
                            expression { ! skipStage(stage: 'test-centos-rpms', cache: commit_pragma_cache) }
                        }
                    }
                    agent {
                        label 'ci_vm1'
                    }
                    steps {
                        testRpm inst_repos: daosRepos(commit_pragma_cache),
                                daos_pkg_version: daosPackagesVersion(commit_pragma_cache)
                   }
                } // stage('Test CentOS 7 RPMs')
                stage('Scan CentOS 7 RPMs') {
                    when {
                        beforeAgent true
                        allOf {
                            not { branch 'weekly-testing' }
                            not { environment name: 'CHANGE_TARGET',
                                              value: 'weekly-testing' }
                            expression { ! skipStage(stage: 'scan-centos-rpms', cache: commit_pragma_cache) }
                        }
                    }
                    agent {
                        label 'ci_vm1'
                    }
                    steps {
                        testRpm inst_repos: daosRepos(commit_pragma_cache),
                                daos_pkg_version: daosPackagesVersion(commit_pragma_cache),
                                inst_rpms: 'clamav clamav-devel',
                                test_script: 'ci/rpm/scan_daos.sh',
                                junit_files: 'maldetect.xml'
                    }
                    post {
                        always {
                            junit 'maldetect.xml'
                        }
                    }
                } // stage('Scan CentOS 7 RPMs')
            } // parallel
        } // stage('Test')
        stage ('Test Report') {
            parallel {
                stage('Bullseye Report') {
                    when {
                      beforeAgent true
                      allOf {
                        expression { ! env.BULLSEYE != null }
                        expression { ! skipStage(stage: 'bullseye',
                                                 def_val: true,
                                                 cache: commit_pragma_cache) }
                      }
                    }
                    agent {
                        dockerfile {
                            filename 'Dockerfile.centos.7'
                            dir 'utils/docker'
                            label 'docker_runner'
                            additionalBuildArgs "-t ${sanitized_JOB_NAME}-centos7 " +
                                '$BUILDARGS_QB_CHECK' +
                                ' --build-arg BULLSEYE=' + env.BULLSEYE +
                                ' --build-arg QUICKBUILD_DEPS="' +
                                  env.QUICKBUILD_DEPS_EL7 + '"' +
                                ' --build-arg REPOS="' + prRepos(commit_pragma_cache) + '"'
                        }
                    }
                    steps {
                        // The coverage_healthy is primarily set here
                        // while the code coverage feature is being implemented.
                        cloverReportPublish(
                                   coverage_stashes: ['centos7-covc-unit-cov'],
                                   coverage_healthy: [methodCoverage: 0,
                                                      conditionalCoverage: 0,
                                                      statementCoverage: 0],
                                   ignore_failure: true)
                    }
                } // stage('Bullseye Report')
            } // parallel
        } // stage ('Test Report')
    } // stages
    post {
        always {
            valgrindReportPublish valgrind_stashes: ['centos7-gcc-unit-valg']
        }
        unsuccessful {
            notifyBrokenBranch branches: target_branch
        }
    } // post
}
