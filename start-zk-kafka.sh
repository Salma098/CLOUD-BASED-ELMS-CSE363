#!/bin/bash
cd ~/kafka_2.13-3.6.1 || exit 1
DATA_DIR=$(grep -E '^dataDir=' config/zookeeper.properties | cut -d'=' -f2)
DATA_DIR=${DATA_DIR:-/tmp/zookeeper}
echo "Using ZK dataDir: $DATA_DIR"
sudo mkdir -p "$DATA_DIR"
echo 1 | sudo tee "$DATA_DIR/myid"
sudo chown -R $(whoami):$(whoami) "$DATA_DIR"
echo "Starting ZooKeeper..."
bin/zookeeper-server-start.sh -daemon config/zookeeper.properties
sleep 3
echo "ZooKeeper processes:"; ps aux | egrep 'zookeeper' | egrep -v 'egrep' || true
echo "Starting Kafka..."
bin/kafka-server-start.sh -daemon config/server.properties
sleep 3
echo "Kafka processes:"; ps aux | egrep 'kafka' | egrep -v 'egrep' || true
echo "Listening ports:"; sudo ss -lntp | egrep '2181|9092' || true
echo "Test nc localhost:2181"; nc -zv 127.0.0.1 2181 || true
echo "Test nc localhost:9092"; nc -zv 127.0.0.1 9092 || true
