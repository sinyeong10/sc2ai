# 파일 경로 설정
file_path1 = 'zelaot/flow-action/semi_sim/full_log.txt'
file_path2 = 'zelaot/flow-action/semi_sim/sim_log.txt'
output_path = 'zelaot/flow-action/semi_sim/data.txt'

# 결과를 저장할 리스트
updated_lines = []
cnt = 0
# 두 파일을 동시에 열어서 처리
with open(file_path1, 'r') as file1, open(file_path2, 'r') as file2:
    for line1, line2 in zip(file1, file2):
        cnt += 1
        if line1 == line2:
            updated_lines.append("")
            continue
        # 각 줄을 튜플로 변환
        entry1 = eval(line1.strip())
        entry2 = eval(line2.strip())
        print(entry1)
        print(entry2)
        # state 정보 추출 및 업데이트
        entry1[1]['state'][2:9] = entry2[1]['state'] # ful_data state[2:9]를 sim_data의 state로
        
        if not(entry1[0]==entry2[0] and entry1[1]["done"]==entry2[1]["done"] and entry1[1]["action"]==entry2[1]["action"]):
            print(cnt,"줄에서 에러")
            break
        # 결과 저장
        print(entry1)
        updated_lines.append(entry1)

# 결과를 새 파일에 쓰기
with open(output_path, 'w') as output_file:
    for line in updated_lines:
        output_file.write(f"{line}\n")

print("파일 처리가 완료되었습니다.")
