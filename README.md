## AgentGuard

### Current stage: PoC
Not yet completed, currently only has signature-based detection for path traversal attempts. The agentic analysis is rudimentary and requires fine-tuning as well.

### Usage
```
(venv) [lkotlus@m1n1m3] [.../CYSE/587/AgentGuard] [ main]
(bash)> python3 main.py -h
usage: main.py [-h] -p PATH -a AGENT_ROOT

File watching and static analysis script.

options:
  -h, --help            show this help message and exit
  -p, --path PATH       Path to the directory you want to watch.
  -a, --agent-root AGENT_ROOT
                        Path to the agent root.
```

Example:
```
(venv) [lkotlus@m1n1m3] [.../CYSE/587/AgentGuard] [ main]
(norm)> python3 main.py -a $cyse/587/adop-cyse/testbed-repo/ -p $cyse/587/adop-cyse/corpus/

    _                    _    ____                     _
   / \   __ _  ___ _ __ | |_ / ___|_   _  __ _ _ __ __| |
  / _ \ / _` |/ _ \ '_ \| __| |  _| | | |/ _` | '__/ _` |
 / ___ \ (_| |  __/ | | | |_| |_| | |_| | (_| | | | (_| |
/_/   \_\__, |\___|_| |_|\__|\____|\__,_|\__,_|_|  \__,_|
        |___/

  watching : /home/lkotlus/Everything/Classes/CYSE/587/adop-cyse/corpus/
  sandbox  : /home/lkotlus/Everything/Classes/CYSE/587/adop-cyse/testbed-repo/
  ----------------------------------------
```
