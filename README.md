# SharkScout

🕵️ Web App for FRC Competition Scouting.

## Running From Build

### Windows Executable

This is the easiest way to run the server on a Windows machine.

1. Install [MongoDB](https://www.mongodb.com/download-center).
2. Download the [latest release](https://github.com/hammerhead226/SharkScout/releases/latest).
3. Run `SharkScout.exe`.

## Running From Docker

This is the easiest way to run the server on a non-Windows machine.

1. Install [Docker](https://www.docker.com/get-started).
2. Install [Docker Compose](https://docs.docker.com/compose/install/).
3. Build and run the containers.

### Build the Containers

This requires an internet connection and only needs to be done when the source has changed.

Run `docker-compose`:

```batch
docker-compose up --build --no-start
```

### Run the Containers

Run `docker-compose`:

```batch
docker-compose up
```

## Running From Source

Note: it is recommended that the server be run using one of the above out-of-the-box solutions.

### Installing Dependencies

1. Install [MongoDB](https://www.mongodb.com/download-center).
2. Install [Python 3](https://www.python.org/downloads/).
3. Windows users: ensure Python 3 (`%LOCALAPPDATA%\Programs\Python\*` and `%LOCALAPPDATA%\Programs\Python\*\Scripts`) and MongoDB (`%PROGRAMFILES%\MongoDB\Server\*\bin`) are in your `PATH` variable.
4. Run `setup.py`:

    ```batch
    python3 setup.py install
    ```

5. Configure your TBA Read API Key in `config.json`.

### Execution

Run `SharkScout.py`:

```batch
python3 SharkScout.py
```

### Building for Windows

Run `build.bat`.

## Updating TBA Information

SharkScout is intended to be used offline and therefore needs to pull a lot of information from The Blue Alliance. It is possible to trigger updates from the web interface but command-line arguments have been provided for batch updates, some examples are below.

To see a full list of command-line arguments execute:

```batch
python3 SharkScout.py -h
```

To update team information only:

```batch
python3 SharkScout.py -ut
```

To update the event listings for all years:

```batch
python3 SharkScout.py -ue 1992-2018
```

To update detailed event information for this year:

```batch
python3 SharkScout.py -ue 2018 -uei 2018
```

In order to be a responsible user of The Blue Alliance's API it is recommended that you only update as little and as infrequently as needed.

## Server Setup

### Remote Server

The easiest setup is to run the server remotely and use cell phones to access it. This can be challenging, though, because competition venues are notorious for poor cell signal.

### Local Server

An alternative to running the server remotely is to run it locally on a laptop at the competition. Because WiFi access points are banned there are some options for this:

1. Run the server and use a network switch with all wired connections to other computers or mobile devices (with OTG ethernet adapters).
2. Run the server on a Linux machine and use [panr](https://github.com/emmercm/panr) to create a Bluetooth PAN network.
3. Run the server on a Windows machine and bridge a connection to a Linux device connected with ethernet, and run [panr](https://github.com/emmercm/panr) on the Linux device with the `-nd` flag to create a Bluetooth PAN network.

## Additional Thoughts

### Database Backups

It is recommended that you make regular backups on multiple drives while `SharkScout` is running. Losing all of your scouting data due to corruption or general failure during a competition would be a disaster. Here is a basic `mongodump` command:

```batch
mongodump /out C:/mongodump-sharkscout /gzip
```
