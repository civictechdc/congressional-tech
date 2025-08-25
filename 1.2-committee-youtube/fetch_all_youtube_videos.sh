#!/bin/bash

for i in {0..12}
do
    youtube-fetch --tinydb_path data/youtube${i}.json -i $i
done
