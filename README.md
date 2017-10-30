# SharkScout
Offline web app with TBA integration for competition scouting.


## Executing From Source
#### Installing Dependencies
1. Install [MongoDB](https://www.mongodb.com/download-center).
2. Install [Python 3](https://www.python.org/downloads/).
3. Windows users: ensure Python 3 (`%LOCALAPPDATA%\Programs\Python\*` and `%LOCALAPPDATA%\Programs\Python\*\Scripts`) and MongoDB (`%PROGRAMFILES%\MongoDB\Server\*\bin`) are in your PATH variable.
4. Install PyPi dependencies:<br/>
`pip3 install backoff cherrypy genshi psutil pymongo pynumparser requests tqdm ws4py`

#### Execution
Execute `SharkScout.py`.

#### Optional: Building Windows Executable
Execute `build.bat`.


## Updating TBA Information
SharkScout is intended to be used offline and therefore needs to pull a lot of information from The Blue Alliance. It is possible to trigger updates from the web interface but command-line arguments have been provided for batch updates, some examples are below.

To see a full list of command-line arguments execute:
```batch
> python SharkScout.py -h
```

To update team information only:
```batch
> python SharkScout.py -ut
```

To update the event listings for all years:
```batch
> python SharkScout.py -ue 1992-2017
```

To update detailed event information for this year:
```batch
> python SharkScout.py -ue 2017 -uei 2017
```

In order to be a responsible user of The Blue Alliance's API it is recommended that you only update as little and as infrequently as needed.


## Server Setup
#### Remote Server
The easiest setup is to run the server remotely and use cell phones to access it. This can be challenging, though, because competition venues are notorious for poor cell signal.

#### Local Server
An alternative to running the server remotely is to run it locally on a laptop at the competition. Because WiFi access points are banned there are 2 options for this:
1. Use a network switch and all wired connections to either laptops or tablets (OTG ethernet adapters).
2. Use [panr](https://github.com/emmercm/panr) on a Linux device to create a Bluetooth PAN network.


## Additional Thoughts
#### Database Backups
It is recommended that you make regular backups on multiple drives while `SharkScout` is running. Losing all of your scouting data due to corruption or general failure during a competition would be a disaster. Here is a basic `mongodump` command:
```batch
> mongodump /out C:/mongodump-sharkscout /gzip
```
