#!/bin/bash

# # Run the experiment 5 times with different output directory names
# for i in {2..5}
# do
#     echo "Running experiment $i"
#     ./run_infer.sh -m o3 -t secb_poc -f ./config/secb_poc.yaml -c 1.0 -e 0.0 -s eval -l :40 -n 75 -w 2
#     echo "Completed experiment $i"
#     mv trajectories/hwiwon/secb_poc__o3-mini__t-0.00__p-0.95__c-1.00___secb_poc_eval trajectories/hwiwon/stat_significance/secb_poc__o3-mini__t-0.00__p-0.95__c-1.00___secb_poc_eval_$i
#     echo "----------------------------------------"
# done


# Run the experiment 5 times with different output directory names
for i in {1..5}
do
    echo "Running experiment $i"
    ./run_infer.sh -m o3 -t secb_patch -f ./config/secb_patch.yaml -c 1.0 -e 0.0 -s eval -l :40 -n 75 -w 2
    echo "Completed experiment $i"
    mv trajectories/hwiwon/secb_patch__o3-mini__t-0.00__p-0.95__c-1.00___secb_patch_eval trajectories/hwiwon/stat_significance/secb_patch__o3-mini__t-0.00__p-0.95__c-1.00___secb_patch_eval_$i
    echo "----------------------------------------"
done
