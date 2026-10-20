import os
import pandas as pd
import io

def clean_markdown_table(file_path):
    if not os.path.exists(file_path):
        print(f"오류: '{file_path}' 파일을 찾을 수 없습니다.")
        return

    print(f"'{file_path}' 파일을 읽어오는 중...")
    
    try:
        # 마크다운 파일을 줄 단위로 읽어서 표 구조(|)가 포함된 라인만 추출
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        table_lines = [line for line in lines if '|' in line]
        
        if not table_lines:
            print("오류: 마크다운 파일 내에 표(|) 데이터가 없습니다.")
            return
            
        # pandas의 read_csv를 활용해 파이프(|) 구분자로 테이블 파싱
        # (첫 번째 줄은 헤더, 두 번째 줄은 구분선이므로 skiprows 등으로 제외하거나 처리)
        csv_data = "".join(table_lines)
        
        # read_csv로 파이프(|) 구분 데이터 읽기 (공백 제거 및 헤더 정리)
        df = pd.read_csv(io.StringIO(csv_data), sep='|').dropna(how='all', axis=1)
        
        # 컬럼 양쪽 공백 제거
        df.columns = df.columns.str.strip()
        
        # 결측치(NaN/빈칸)를 0으로 치환
        df_cleaned = df.fillna(0)
        
        output_csv = "cleaned_menu_table_1.csv"
        df_cleaned.to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"정제된 표 저장 완료: {output_csv}")
        print("모든 결측치 전처리가 완료되었습니다.")

    except Exception as e:
        print(f"마크다운 파싱 중 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    target_file = "fb_agent/data/f_b_menu_data.md"
    clean_markdown_table(target_file)