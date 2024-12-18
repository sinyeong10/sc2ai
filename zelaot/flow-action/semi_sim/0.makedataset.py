import sys
import os

def read_and_parse_data(file_path):

    if os.path.exists(r'zelaot\flow-action\data_set\semi_sim_data\result_data.txt'):
        with open(r'zelaot\flow-action\data_set\semi_sim_data\result_data.txt', 'r') as file:
            result_data = eval(file.read())
    else:
        result_data = {}
    # 파일 경로 설정
    # 결과를 저장할 리스트
    updated_lines = []
    cnt = 0
    new = False
    first_data = [0,0,12,15,12,1,0,0,0,0] 
    # 두 파일을 동시에 열어서 처리
    with open(file_path, 'r') as file:
        for line in file:
            cnt += 1
            print(cnt,"line :", line.strip())
            if new:
                first_data = [0,0,12,15,12,1,0,0,0,0] 
            if line[0] == "[":
                all_order = eval(line)
                key = eval(line)
                new = True
                updated_lines.append("")
            elif line[0] == "(":
                cur_data = eval(line)
                new = False
                #6이 발전 정도를 의미
                #이 명령으로 인해 기대되는 상태를 반환!
                cur_action = all_order.pop(0)
                if cur_action == 0:
                    first_data[2]+=1
                    first_data[4]+=1
                elif cur_action == 1:
                    if first_data[6] < 1:
                        first_data[6] = 1
                    first_data[3]+=8
                elif cur_action == 2:
                    first_data[6]=2
                    first_data[7]+=1
                elif cur_action == 3:
                    first_data[8]+=1
                elif cur_action == 9: #명령이 끝남을 의미   
                    print("하나 처리")
                    print(cur_data, cur_data[1]["state"][:2]+cur_data[1]["state"][-1:])
                    if tuple(key) in result_data:
                        result_data[tuple(key)].append(cur_data[1]["state"][:2]+cur_data[1]["state"][-1:])
                    else:
                        result_data[tuple(key)] = [cur_data[1]["state"][:2]+cur_data[1]["state"][-1:]]
                else:
                    print(cur_action, "정상명령이 아닌데?")
                    sys.exit()
                # print(cur_data)
                # print(cur_data[1]["state"][2:9])
                cur_data[1]["state"][2:9] = first_data[2:9]
                # print("들어감", cur_data)

                updated_lines.append(cur_data)
            print(cnt, first_data,"\n")
    # print(result_data)
    
    with open(r'zelaot\flow-action\data_set\semi_sim_data\result_data.txt', 'w') as file:
        file.write(str(result_data))
    return updated_lines

# 파일 경로에 맞게 설정
file_path = r'zelaot\flow-action\data_set\semi_sim_data\5__full_log_1.txt'
parsed_data = read_and_parse_data(file_path)

# # 데이터 출력
# for item in parsed_data:
#     print(item)

output_path = r'zelaot\flow-action\data_set\semi_sim_data\5__full_data_1.txt'
# 결과를 새 파일에 쓰기
with open(output_path, 'w') as output_file:
    for line in parsed_data:
        output_file.write(f"{line}\n")
