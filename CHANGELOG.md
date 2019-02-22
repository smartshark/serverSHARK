# 2.0.2 (in progress)
- add search field for name and mongo_id to projects in admin.py
- upgrade django to 1.11.20
- add commit verification command (thanks Benjamin!)
- add the ability to re-run collection for commits that had verification problems
- add the ability to check coastSHARK fails from verification to parse errors in job logs

# 2.0.1
- vagrantfile now includes maven and gradle for java plugins
- plugin install from github now merged
- plugin versioning scheme converted to semver
- auto fill for repository_url (if parameter name in the plugin is correctly named)
- delete_project now includes progress output
- notification for pluginexecutions included in notification command

# 0.1.3
- refactored localqueue and hpc connector common methods to new util module connector
- include deletion of projects via command
- fetch commits from mongodb instead of git clone

# 0.1.2
- updated vagrantfile template to ubuntu 18.04
- include deletion of projects

# 0.1.1
- added server command to set job stati on all jobs matching certain criterias (set_job_state)
- added server command to fetch error log for a set of jobs and looking for certain strings (filter_job_logs)
- added re-run of plugin executions and jobs

# 0.1.0
- added changelog and version to frontend
- improved admin view of jobs with filters and revision_hash search
- fix pagination for plugin execution status