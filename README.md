## AgentGuard

### Current stage: PoC
Currently implements signature-based detection for path-traversal on `git_show_worktree` and `git_init` tool calls (CVE-2025-68143). Signature-based detection for argument-injection (`git_diff` pathspec flag smuggling, CVE-2025-68144) as well as other markers of excessive agency (e.g., deviation from the golden path) have not been implemented yet. The agentic evaluation layer receives low-confidence findings and is capable of detecting risk that is not measured in the signature-based approach, although this is currently unreliable. More work needs to be done on supporting more signatures and fine-tuning the analysis agent.

The general flow of data works as follows:
1. A file change event is detected within the `adop-cyse/corpus/` directory
2. This event is passed to a file change event handler 
3. The file change is analyzed, if it contains complete log entries, those entries are parsed.
4. For each log entry:
    - It undergoes signature-based detection and is given a risk score
    - If the risk score exceeds 80%, it is immediately reported
    - If the risk score is less than 80%, the `scenario_tag` and `annotations` fields are stripped, and the log is passed to the analysis agent for further review

### Installation
Both Linux and Windows require `python3` to be installed. The name of the binary on your `PATH` is detected automatically.

#### Linux
```bash
$ ./install.sh
```

#### Windows
```powershell
$ Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # May be required to execute the installation script
$ .\install.ps1
```

### Usage
```
$ python3 main.py -h
usage: main.py [-h] -p PATH -a AGENT_ROOT

File watching and static analysis script.

options:
  -h, --help            show this help message and exit
  -p, --path PATH       Path to the directory you want to watch.
  -a, --agent-root AGENT_ROOT
                        Path to the agent root.
```

If you're running the ADOP testbed, you just need to provide the path to the agent's sandbox directory (`adop-cyse/testbed-repo/`) and the path to the ADOP log corpus (`adop-cyse/corpus/`). For example:

```
$ python3 main.py -a /path/to/adop-cyse/testbed-repo/ -p /path/to/adop-cyse/corpus/

    _                    _    ____                     _
   / \   __ _  ___ _ __ | |_ / ___|_   _  __ _ _ __ __| |
  / _ \ / _` |/ _ \ '_ \| __| |  _| | | |/ _` | '__/ _` |
 / ___ \ (_| |  __/ | | | |_| |_| | |_| | (_| | | | (_| |
/_/   \_\__, |\___|_| |_|\__|\____|\__,_|\__,_|_|  \__,_|
        |___/

  watching : /path/to/adop-cyse/corpus/
  sandbox  : /path/to/adop-cyse/testbed-repo/
  ----------------------------------------
```
