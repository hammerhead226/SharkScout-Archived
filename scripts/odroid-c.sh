#!/bin/bash

# Linux bash script to:
# - Install the 3.5inch touchscreen shield
# - Register itself to run on startup on the 3.5inch touchscreen shield
# - Install/update necessary dependencies when connected to the internet
# - Start panr, panr-acceptr, and SharkScout
# - Continually loop and display process and network information

cd "$(dirname "$0")"


# Require internet connection for setup
(nc -z -w 1 8.8.8.8 53 || nc -z -w 1 8.8.4.4 53) && (
	# Initial full update
	sudo rm /var/lib/dpkg/lock
	sudo apt-get -y update
	sudo apt-get -y upgrade
	sudo apt-get -y dist-upgrade
	sudo apt-get -y install wget

	# Set timezone to EST
	sudo rm /etc/localtime
	sudo ln -s /usr/share/zoneinfo/US/Eastern /etc/localtime

	# Turn off startup fsck (potentially dangerous)
	sudo sed -i 's/1$/0/g' /etc/fstab
	sudo tune2fs -c 0 -i 0 -l /dev/mmcblk0p2

	# ODROID C1/C2 LCD
	if [ "$(systemctl | grep odroid-lcd35)" == "" ]; then
		wget -N http://dietpi.com/downloads/misc/community/install_odroid_LCD35.sh
		chmod +x install_odroid_LCD35.sh
		./install_odroid_LCD35.sh 1
		rm install_odroid_LCD35.sh

		# Put this script in startup
		if [ "$(lsb_release -a 2>&1 | grep Release | awk '{print $2}')" == "16.04" ]; then
			if [ ! -e "/etc/systemd/system/getty@tty1.service.d" ]; then
				mkdir --parents "/etc/systemd/system/getty@tty1.service.d"
			fi
			sudo rm /etc/systemd/system/getty@tty1.service.d/override.conf
			echo "[Service]" | sudo tee --append /etc/systemd/system/getty@tty1.service.d/override.conf > /dev/null
			echo "ExecStart=" | sudo tee --append /etc/systemd/system/getty@tty1.service.d/override.conf > /dev/null
			echo "ExecStart=$(realpath $0)" | sudo tee --append /etc/systemd/system/getty@tty1.service.d/override.conf > /dev/null
			echo "StandardInput=tty" | sudo tee --append /etc/systemd/system/getty@tty1.service.d/override.conf > /dev/null
			echo "StandardOutput=tty" | sudo tee --append /etc/systemd/system/getty@tty1.service.d/override.conf > /dev/null
		fi
	fi

	# panr + bt-pan
	sudo apt-get -y install bluez bridge-utils ipcalc python python-dbus udhcpd
	wget -N https://raw.githubusercontent.com/mk-fg/fgtk/master/bt-pan
	chmod +x bt-pan
	wget -N https://raw.githubusercontent.com/emmercm/panr/master/panr
	chmod +x panr
	# panr-acceptr
	sudo apt-get -y install python3 python3-pip
	pip3 install --upgrade pip
	pip3 install pexpect
	wget -N https://raw.githubusercontent.com/emmercm/panr/master/panr-acceptr
	chmod +x panr-acceptr

	# mongodb
	sudo apt-get -y install curl
	MONGODB_VER=$(curl -s http://repo.mongodb.com/apt/ubuntu/dists/xenial/mongodb-enterprise/ | grep "[0-9]\+\.[0-9]\+" | sed 's/\s*<[^>]\+>//g' | tail -1)
	echo "deb [ arch=amd64,arm64,ppc64el,s390x ] http://repo.mongodb.com/apt/ubuntu xenial/mongodb-enterprise/${MONGODB_VER} multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-enterprise.list > /dev/null
	sudo apt-get -y update
	sudo apt-get --allow-unauthenticated -y install mongodb-enterprise

	# SharkScout
	sudo apt-get -y install git
	git clone https://github.com/hammerhead226/SharkScout.git
	chmod +x SharkScout/SharkScout.py
	chmod +x SharkScout/setup.py
	./SharkScout/setup.py install

	# Info display tool(s)
	sudo apt-get -y install bluez-tools
)


# Execute panr and panr-acceptr
./panr &> /dev/null &
(
	sleep 5s
	./panr-acceptr &> /dev/null
) &

# Execute SharkScout
(
	sleep 10s
	cd SharkScout
	sed -i 's/\r\n/\n/g' *.py
	while [ "" == "" ]; do
		sudo ./SharkScout.py --port 80 --no-browser &> /dev/null
	done
) &
(
	while [ "" == "" ]; do
		sleep 5m
		mongodump --out mongodump-$(date +'%Y%m%d_%H%M%S%z') --db shark_scout --collection scouting --gzip &> /dev/null
	done
) &


# Echo info to be printed
info() {
	uname -a
	ps -Afw | grep "python.\+SharkScout\|mongod" | grep -v grep | awk '{printf "%s  ",$2;for(i=8;i<=NF;i++)printf "%s ",$i;printf "\n"}'
	echo ""
	ip addr | grep -A 2 "^\w" | grep -v "\-\-" | awk '{print $2}' | sed 'N;N;s/\n/\t/g' | grep -v "lo\|bnep" | sort
	echo ""
	for HCI in $(hciconfig | grep "^\w" | awk '{print $1}' | sed 's/://' | sort); do
		hcitool dev | grep "${HCI}" | awk -v HCI="${HCI}" '{print HCI "  " $2}'
		bt-device --adapter "${HCI}" --list | grep -f <(hcitool -i "${HCI}" con | tail -n +2 | awk '{print $3}') | sed 's/[()]//g' | sed 's/ /\t/' | sort
		echo ""
	done
}
export -f info

# Repeatedly call a command and print the output to the entire screen
watchit() {
	HOME=$(tput cup 0 0)
	ED=$(tput ed)
	EL=$(tput el)
	printf '%s%s' "$HOME" "$ED"
	while true; do
		ROWS=$(tput lines)
		COLS=$(tput cols)
		CMD="$@"
		${SHELL:=sh} -c "$CMD" | head -n $ROWS | while IFS= read LINE; do
			printf '%-*.*s%s\n' $COLS $COLS "$(echo "$LINE" | sed 's/\t/  /g')" "$EL"
		done
		printf '%s%s' "$ED" "$HOME"
		sleep 1
	done
}

watchit info
