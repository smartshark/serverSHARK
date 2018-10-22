# 0.1.3
- refactored localqueue and hpc connector common methods to new util module connector
- include deletion of projects via command

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