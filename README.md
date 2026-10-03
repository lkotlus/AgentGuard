## AgentGuard

### Current stage: PoC
Not yet completed, currently only has signature-based detection for path traversal attempts. The agentic analysis is rudimentary and requires fine-tuning as well.

### Installation
Both Linux and Windows require for you to have Python3 installed.

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
Help:
```bash
$ python3 main.py -h
usage: main.py [-h] -p PATH -a AGENT_ROOT

File watching and static analysis script.

options:
  -h, --help            show this help message and exit
  -p, --path PATH       Path to the directory you want to watch.
  -a, --agent-root AGENT_ROOT
                        Path to the agent root.
```

So, if you're running the ADOP testbed, you just need to provide the path to the agent's sandbox directory (`adop-cyse/testbed-repo/`) and the path to the ADOP log corpus (`adop-cyse/corpus/`). For example:
```bash
$ python3 main.py -a $cyse/587/adop-cyse/testbed-repo/ -p $cyse/587/adop-cyse/corpus/

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
