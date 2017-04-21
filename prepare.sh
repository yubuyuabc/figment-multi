#first add the project directory to your PYTHONPATH
#This script should be run only once, before starting the experiments, to build the datastreams
cd data
wget http://cistern.cis.lmu.de/figment2/embeddings/skip,200dim.txt
wget http://cistern.cis.lmu.de/figment2/embeddings/sskip,200dim.txt
wget http://cistern.cis.lmu.de/figment2/embeddings/fasttext,200dim.txt

mkdir skip
cd skip
cp ../datasets/* .
mv ../skip,200dim.txt .
mkdir fueldata
python ../../src/make_fuel_dataset.py config &
wait
rm Etrain.names Edev.names Etest.names types

mkdir sskip
cd sskip
cp ../datasets/* .
mv ../sskip,200dim.txt .
mv ../fasttext,200dim.txt .
mkdir fueldata
python ../../src/make_fuel_dataset.py config &
rm Etrain.names Edev.names Etest.names types
