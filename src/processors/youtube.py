"""
영상팀(유튜브) 데이터 처리 모듈
- Work status CSV: '[영상팀] 업무 현황*.csv'
- YouTube Studio content DB xlsx: '*유튜브 콘텐츠 DB.xlsx'
- YouTube Studio traffic DB xlsx: '*유튜브 트래픽 DB.xlsx'
"""

import re
import pandas as pd
import numpy as np
from io import BytesIO
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class LoadedFile:
    name: str
    df: Optional[pd.DataFrame] = None
    raw_bytes: Optional[bytes] = None


def parse_date_to_year_month(date_value) -> Optional[str]:
    """Parse various date formats to YYYY-MM."""
    if pd.isna(date_value):
        return None

    try:
        if isinstance(date_value, pd.Timestamp):
            return date_value.strftime('%Y-%m')

        date_str = str(date_value).strip()
        if not date_str or date_str == 'nan':
            return None

        # Try 'Nov 28, 2025' format
        try:
            dt = pd.to_datetime(date_str, format='%b %d, %Y')
            return dt.strftime('%Y-%m')
        except:
            pass

        # Try standard formats
        dt = pd.to_datetime(date_str, errors='coerce')
        if pd.notna(dt):
            return dt.strftime('%Y-%m')
    except Exception:
        pass

    return None


def extract_month_from_filename(filename: str) -> Optional[str]:
    """Extract month from filename like '11월' or '12월'."""
    from datetime import datetime

    # "2025-12", "202512" 등 연도 포함 패턴 우선
    match = re.search(r'(\d{4})[-_]?(\d{2})', filename)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    # "1월", "12월" 등 연도 없는 패턴 → 현재 연도
    match = re.search(r'(\d{1,2})월', filename)
    if match:
        month = int(match.group(1))
        return f"{datetime.now().year}-{month:02d}"
    return None


def process_work_csv(files: List[LoadedFile]) -> Dict[str, Any]:
    """Process work status CSV: '[영상팀] 업무 현황*.csv'

    This is a Notion-style CSV with forward-fill needed for grouped data.
    Each *ID groups multiple rows (one per video in a contract).
    """
    all_work = []
    all_videos = []

    for f in files:
        if not re.search(r'\[영상팀\].*업무.*현황.*\.csv', f.name, re.IGNORECASE):
            continue

        try:
            if f.df is not None:
                df = f.df.copy()
            elif f.raw_bytes:
                df = pd.read_csv(BytesIO(f.raw_bytes), encoding='utf-8-sig')
            else:
                continue

            # Find column mappings
            col_mapping = {}
            for col in df.columns:
                col_str = str(col).strip()
                if col_str == '*ID':
                    col_mapping['id'] = col
                elif col_str == '거래처 명':
                    col_mapping['clinic'] = col
                elif col_str == '영상 종류':
                    col_mapping['video_type'] = col
                elif col_str == '계약 건수':
                    col_mapping['contract_count'] = col
                elif col_str == '완료 건수':
                    col_mapping['completed_count'] = col
                elif col_str == '상태':
                    col_mapping['status'] = col
                elif '기획 내역-기획 완료' in col_str:
                    col_mapping['planning_date'] = col
                elif '촬영 내역-촬영 날짜' in col_str:
                    col_mapping['filming_date'] = col
                elif '편집 내역-편집 완료일' in col_str:
                    col_mapping['editing_date'] = col
                elif '편집 내역-업로드 날짜' in col_str:
                    col_mapping['upload_date'] = col
                elif '편집 내역-내용 및 제목' in col_str:
                    col_mapping['content_details'] = col
                elif '계약 상 작업 연도/ 월' in col_str:
                    col_mapping['contract_month'] = col
                elif '편집 내역-편집 종류' in col_str:
                    col_mapping['edit_type'] = col

            print(f"[youtube] col_mapping keys: {list(col_mapping.keys())}")
            if 'edit_type' not in col_mapping:
                print(f"[youtube] WARNING: '편집 내역-편집 종류' 컬럼 미감지. CSV 컬럼: {list(df.columns[:10])}...")

            # Forward-fill for Notion-style grouping
            fill_cols = ['id', 'clinic', 'video_type', 'contract_count', 'completed_count',
                         'status', 'contract_month']
            for key in fill_cols:
                if key in col_mapping:
                    df[col_mapping[key]] = df[col_mapping[key]].ffill()

            # Group by ID to get contract-level data
            if 'id' in col_mapping:
                grouped = df.groupby(col_mapping['id'])

                for group_id, group_df in grouped:
                    first_row = group_df.iloc[0]

                    clinic = str(first_row.get(col_mapping.get('clinic', ''), '')).strip()
                    video_type = str(first_row.get(col_mapping.get('video_type', ''), '')).strip()
                    status = str(first_row.get(col_mapping.get('status', ''), '')).strip()

                    # Get year_month from contract_month or upload dates
                    year_month = None
                    contract_month_str = str(first_row.get(col_mapping.get('contract_month', ''), '')).strip()
                    if contract_month_str and contract_month_str != 'nan':
                        # Parse "2025년 9월" format
                        match = re.search(r'(\d{4})년\s*(\d{1,2})월', contract_month_str)
                        if match:
                            year_month = f"{match.group(1)}-{int(match.group(2)):02d}"

                    # Fallback to upload date
                    if not year_month and 'upload_date' in col_mapping:
                        for _, row in group_df.iterrows():
                            upload_date = row.get(col_mapping['upload_date'], '')
                            ym = parse_date_to_year_month(upload_date)
                            if ym:
                                year_month = ym
                                break

                    # Calculate lead time from planning to last upload
                    lead_time_days = None
                    if 'planning_date' in col_mapping and 'upload_date' in col_mapping:
                        plan_dt = pd.to_datetime(first_row.get(col_mapping['planning_date'], ''), errors='coerce')
                        # Get last upload date
                        for _, row in group_df.iloc[::-1].iterrows():
                            upload_dt = pd.to_datetime(row.get(col_mapping['upload_date'], ''), errors='coerce')
                            if pd.notna(upload_dt):
                                if pd.notna(plan_dt):
                                    lead_time_days = (upload_dt - plan_dt).days
                                break

                    # 1행 컬럼값에서 계약 건수 / 완료 건수 직접 읽기
                    raw_contract = first_row.get(col_mapping.get('contract_count', ''), 0)
                    raw_completed = first_row.get(col_mapping.get('completed_count', ''), 0)
                    try:
                        contract_count = float(raw_contract) if pd.notna(raw_contract) else 0
                    except (ValueError, TypeError):
                        contract_count = 0
                    try:
                        completed_count = float(raw_completed) if pd.notna(raw_completed) else 0
                    except (ValueError, TypeError):
                        completed_count = 0

                    is_completed = ('완료' in status)

                    if clinic and clinic != 'nan':
                        all_work.append({
                            'year_month': year_month,
                            'clinic': clinic,
                            'video_type': video_type,
                            'contract_count': contract_count,
                            'completed_count': completed_count,
                            'status': status,
                            'lead_time_days': lead_time_days,
                            'is_completed': is_completed,
                        })

                    # Collect individual video records
                    if 'content_details' in col_mapping:
                        for _, row in group_df.iterrows():
                            content = str(row.get(col_mapping['content_details'], '')).strip()
                            upload_date = row.get(col_mapping.get('upload_date', ''), '')
                            edit_type = str(row.get(col_mapping.get('edit_type', ''), '')).strip() if 'edit_type' in col_mapping else ''
                            if content and content != 'nan':
                                all_videos.append({
                                    'clinic': clinic,
                                    'title': content,
                                    'upload_date': str(upload_date) if pd.notna(upload_date) else None,
                                    'year_month': parse_date_to_year_month(upload_date) or year_month,
                                    'contract_month': year_month,
                                    'edit_type': edit_type,
                                })

        except Exception as e:
            print(f"Error processing work file {f.name}: {e}")
            continue

    if not all_work:
        return {}

    work_df = pd.DataFrame(all_work)

    # Aggregate by year_month using loop to avoid FutureWarning
    monthly_data = {}
    for _, row in work_df.iterrows():
        ym = row['year_month']
        if ym not in monthly_data:
            monthly_data[ym] = {
                'year_month': ym,
                'contract_count': 0,
                'completed_count': 0,
                'lead_times': [],
            }
        monthly_data[ym]['contract_count'] += row['contract_count']
        monthly_data[ym]['completed_count'] += row['completed_count']
        if row['lead_time_days'] is not None:
            monthly_data[ym]['lead_times'].append(row['lead_time_days'])

    monthly_summary = []
    for ym, data in monthly_data.items():
        avg_lead_time = np.mean(data['lead_times']) if data['lead_times'] else None
        completion_rate = (data['completed_count'] / data['contract_count'] * 100) if data['contract_count'] > 0 else 0
        monthly_summary.append({
            'year_month': data['year_month'],
            'contract_count': data['contract_count'],
            'completed_count': data['completed_count'],
            'lead_time_days': avg_lead_time,
            'completion_rate': completion_rate,
        })

    # 거래처명 수집 (불일치 감지용)
    clinic_names = work_df['clinic'].dropna().unique().tolist() if 'clinic' in work_df.columns else []

    return {
        'monthly_summary': monthly_summary,
        'all_work': work_df.to_dict('records'),
        'all_videos': all_videos,
        'clinic_names': clinic_names
    }


def process_content_db_xlsx(files: List[LoadedFile]) -> Dict[str, Any]:
    """Process YouTube Studio content DB xlsx: '*유튜브 콘텐츠 DB.xlsx'

    Structure:
    - Row 0 is header: '콘텐츠', '동영상 제목', '동영상 게시 시간', '길이', '조회수', etc.
    - Row 1 is '합계' (totals)
    - '콘텐츠' column contains video IDs (not content type)
    - '동영상 제목' is the actual title
    - Date format: 'Oct 28, 2025'
    """
    all_content_data = []
    all_totals = []
    file_months = []

    for f in files:
        if not re.search(r'유튜브.*콘텐츠.*DB\.xlsx', f.name, re.IGNORECASE):
            continue

        try:
            # Extract month from filename if present
            file_month = extract_month_from_filename(f.name)
            if file_month:
                file_months.append(file_month)

            # Check df first, then raw_bytes
            if f.df is not None:
                df_raw = f.df.copy()
                # If loaded with header=None, first row is the header
                # Check if first column name is integer (no header) vs string (has header)
                first_col = df_raw.columns[0]
                if isinstance(first_col, (int, np.integer)):
                    # Need to set first row as header
                    df = df_raw.iloc[1:].copy()
                    df.columns = df_raw.iloc[0].values
                    df = df.reset_index(drop=True)
                else:
                    df = df_raw
            elif f.raw_bytes:
                df = pd.read_excel(BytesIO(f.raw_bytes))
            else:
                continue

            # Find column mappings
            col_mapping = {}
            for col in df.columns:
                col_str = str(col).strip()
                if col_str == '콘텐츠':
                    col_mapping['content'] = col
                elif col_str == '동영상 제목':
                    col_mapping['title'] = col
                elif col_str == '동영상 게시 시간':
                    col_mapping['publish_time'] = col
                elif col_str == '조회수':
                    col_mapping['views'] = col
                elif col_str == '노출수':
                    col_mapping['impressions'] = col
                elif col_str == '노출 클릭률 (%)':
                    col_mapping['ctr'] = col
                elif col_str == '시청 시간(단위: 시간)':
                    col_mapping['watch_time'] = col
                elif col_str == '구독자':
                    col_mapping['subscribers'] = col

            for _, row in df.iterrows():
                content_id = str(row.get(col_mapping.get('content', ''), '')).strip()

                if content_id == '합계':
                    # Total row
                    views_val = pd.to_numeric(row.get(col_mapping.get('views', ''), 0), errors='coerce')
                    impressions_val = pd.to_numeric(row.get(col_mapping.get('impressions', ''), 0), errors='coerce')
                    ctr_val = pd.to_numeric(row.get(col_mapping.get('ctr', ''), 0), errors='coerce')
                    watch_time_val = pd.to_numeric(row.get(col_mapping.get('watch_time', ''), 0), errors='coerce')
                    subscribers_val = pd.to_numeric(row.get(col_mapping.get('subscribers', ''), 0), errors='coerce')

                    all_totals.append({
                        'file_month': file_month,
                        'total_views': int(views_val) if pd.notna(views_val) else 0,
                        'total_impressions': int(impressions_val) if pd.notna(impressions_val) else 0,
                        'avg_ctr': float(ctr_val) if pd.notna(ctr_val) else 0.0,
                        'total_watch_time': float(watch_time_val) if pd.notna(watch_time_val) else 0.0,
                        'new_subscribers': int(subscribers_val) if pd.notna(subscribers_val) else 0
                    })
                else:
                    # Individual video row
                    title = str(row.get(col_mapping.get('title', ''), '')).strip()
                    views_val = pd.to_numeric(row.get(col_mapping.get('views', ''), 0), errors='coerce')
                    impressions_val = pd.to_numeric(row.get(col_mapping.get('impressions', ''), 0), errors='coerce')
                    ctr_val = pd.to_numeric(row.get(col_mapping.get('ctr', ''), 0), errors='coerce')
                    publish_time = row.get(col_mapping.get('publish_time', ''), '')
                    year_month = parse_date_to_year_month(publish_time) or file_month

                    views = int(views_val) if pd.notna(views_val) else 0
                    impressions = int(impressions_val) if pd.notna(impressions_val) else 0
                    ctr = float(ctr_val) if pd.notna(ctr_val) else 0.0

                    if title and title != 'nan' and content_id and content_id != 'nan':
                        all_content_data.append({
                            'video_id': content_id,
                            'title': title,
                            'views': views,
                            'impressions': impressions,
                            'ctr': ctr,
                            'year_month': year_month,
                            'file_month': file_month
                        })

        except Exception as e:
            print(f"Error processing content DB file {f.name}: {e}")
            continue

    # Aggregate totals across files
    result = {
        'file_months': sorted(set(file_months)) if file_months else [],
        'monthly_totals': all_totals
    }

    # Combined total (latest month or sum)
    if all_totals:
        latest = all_totals[-1] if all_totals else {}
        result['total'] = {
            'total_views': latest.get('total_views', 0),
            'total_impressions': latest.get('total_impressions', 0),
            'avg_ctr': latest.get('avg_ctr', 0),
            'total_watch_time': latest.get('total_watch_time', 0),
            'new_subscribers': latest.get('new_subscribers', 0)
        }

    if all_content_data:
        content_df = pd.DataFrame(all_content_data)

        # 월별 TOP5 분리
        monthly_top5 = {}
        for month in result['file_months']:
            month_data = content_df[content_df['file_month'] == month]
            if not month_data.empty:
                monthly_top5[month] = month_data.nlargest(5, 'views')[['title', 'views', 'ctr']].to_dict('records')

        # Get top 5 by views (across all months or latest month)
        top5 = content_df.nlargest(5, 'views')[['title', 'views', 'ctr']].to_dict('records')
        result['top5_videos'] = top5
        result['all_videos'] = all_content_data
        result['monthly_top5'] = monthly_top5  # 월별 TOP5 동영상

    return result


def process_traffic_db_xlsx(files: List[LoadedFile]) -> Dict[str, Any]:
    """Process YouTube Studio traffic DB xlsx: '*유튜브 트래픽 DB.xlsx'

    Structure:
    - Row 0 is header: '트래픽 소스', '조회수', '시청 시간(단위: 시간)', etc.
    - Row 1 is '합계' (totals)
    - Columns: '트래픽 소스', '조회수', '시청 시간(단위: 시간)', '평균 시청 지속 시간', '노출수', '노출 클릭률 (%)'
    """
    all_traffic_data = []
    all_totals = []
    file_months = []

    for f in files:
        if not re.search(r'유튜브.*트래픽.*DB\.xlsx', f.name, re.IGNORECASE):
            continue

        try:
            # Extract month from filename if present
            file_month = extract_month_from_filename(f.name)
            if file_month:
                file_months.append(file_month)

            # Check df first, then raw_bytes
            if f.df is not None:
                df_raw = f.df.copy()
                # If loaded with header=None, first row is the header
                first_col = df_raw.columns[0]
                if isinstance(first_col, (int, np.integer)):
                    # Need to set first row as header
                    df = df_raw.iloc[1:].copy()
                    df.columns = df_raw.iloc[0].values
                    df = df.reset_index(drop=True)
                else:
                    df = df_raw
            elif f.raw_bytes:
                df = pd.read_excel(BytesIO(f.raw_bytes))
            else:
                continue

            # Find column mappings
            col_mapping = {}
            for col in df.columns:
                col_str = str(col).strip()
                if col_str == '트래픽 소스':
                    col_mapping['source'] = col
                elif col_str == '조회수':
                    col_mapping['views'] = col
                elif col_str == '노출수':
                    col_mapping['impressions'] = col
                elif col_str == '노출 클릭률 (%)':
                    col_mapping['ctr'] = col
                elif col_str == '시청 시간(단위: 시간)':
                    col_mapping['watch_time'] = col

            for _, row in df.iterrows():
                source = str(row.get(col_mapping.get('source', ''), '')).strip()
                views_val = pd.to_numeric(row.get(col_mapping.get('views', ''), 0), errors='coerce')
                impressions_val = pd.to_numeric(row.get(col_mapping.get('impressions', ''), 0), errors='coerce')
                ctr_val = pd.to_numeric(row.get(col_mapping.get('ctr', ''), 0), errors='coerce')
                watch_time_val = pd.to_numeric(row.get(col_mapping.get('watch_time', ''), 0), errors='coerce')

                views = int(views_val) if pd.notna(views_val) else 0
                impressions = int(impressions_val) if pd.notna(impressions_val) else 0
                ctr = float(ctr_val) if pd.notna(ctr_val) else 0.0
                watch_time = float(watch_time_val) if pd.notna(watch_time_val) else 0.0

                if source == '합계':
                    all_totals.append({
                        'file_month': file_month,
                        'total_views': views,
                        'total_impressions': impressions,
                        'avg_ctr': ctr,
                        'total_watch_time': watch_time
                    })
                else:
                    if source and source != 'nan':
                        all_traffic_data.append({
                            'source': source,
                            'views': views,
                            'impressions': impressions,
                            'ctr': ctr,
                            'watch_time': watch_time,
                            'file_month': file_month
                        })

        except Exception as e:
            print(f"Error processing traffic DB file {f.name}: {e}")
            continue

    result = {
        'file_months': sorted(set(file_months)) if file_months else [],
        'monthly_totals': all_totals
    }

    # Combined total (latest month)
    if all_totals:
        latest = all_totals[-1] if all_totals else {}
        result['total'] = {
            'total_views': latest.get('total_views', 0),
            'total_impressions': latest.get('total_impressions', 0),
            'avg_ctr': latest.get('avg_ctr', 0),
            'total_watch_time': latest.get('total_watch_time', 0)
        }

    # Aggregate traffic by source (latest month)
    if all_traffic_data:
        traffic_df = pd.DataFrame(all_traffic_data)

        # 월별 트래픽 소스 분리
        monthly_traffic = {}
        for month in file_months:
            month_data = traffic_df[traffic_df['file_month'] == month]
            if not month_data.empty:
                # 조회수 기준 상위 5개
                monthly_traffic[month] = month_data.nlargest(5, 'views').to_dict('records')

        # Get latest month's data for by_source
        latest_month = file_months[-1] if file_months else None
        by_source = [t for t in all_traffic_data if t.get('file_month') == latest_month]
        result['by_source'] = by_source
        result['all_traffic'] = all_traffic_data
        result['monthly_traffic'] = monthly_traffic  # 월별 트래픽 소스

    return result


def classify_video_type(video_type: str) -> str:
    """
    영상 종류를 롱폼/숏폼으로 분류합니다.
    - 롱폼: 일반 영상, 긴 영상, 메인 콘텐츠
    - 숏폼: 쇼츠, 릴스, 짧은 영상
    """
    if not video_type or pd.isna(video_type):
        return '기타'

    video_type_lower = str(video_type).lower().strip()

    # 숏폼 키워드
    shortform_keywords = ['숏폼', '쇼츠', 'shorts', 'short', '릴스', 'reels', '짧은']
    for keyword in shortform_keywords:
        if keyword in video_type_lower:
            return '숏폼'

    # 롱폼 키워드
    longform_keywords = ['롱폼', '긴', 'long', '메인', '본편', '풀영상']
    for keyword in longform_keywords:
        if keyword in video_type_lower:
            return '롱폼'

    # 기본값은 롱폼 (일반 영상)
    if video_type_lower and video_type_lower != 'nan':
        return '롱폼'

    return '기타'


def process_youtube(files: List[LoadedFile]) -> Dict[str, Any]:
    """
    Main processor for YouTube/video team.

    Args:
        files: List of LoadedFile objects

    Returns:
        dict with department, month, prev_month, current_month_data, prev_month_data,
        growth_rate, kpi, tables, charts, clean_data

    분석 로직:
    1. 영상 종류별(롱폼/숏폼) 그룹화하여 계약/완료/이월 건수 표시
    2. 전월 대비 증감률 계산
    """
    work_result = process_work_csv(files)
    content_result = process_content_db_xlsx(files)
    traffic_result = process_traffic_db_xlsx(files)

    # Determine months from all sources (work CSV 우선)
    work_months = set()
    if work_result.get('monthly_summary'):
        work_months = {s['year_month'] for s in work_result['monthly_summary'] if s.get('year_month')}

    # 콘텐츠/트래픽 파일 월 수집
    file_months = set()
    if content_result.get('file_months'):
        file_months.update(content_result['file_months'])
    if traffic_result.get('file_months'):
        file_months.update(traffic_result['file_months'])

    # 파일 월이 work 월과 연도가 안 맞으면 work 연도 기준으로 재조정
    if work_months and file_months and not (file_months & work_months):
        work_years = sorted({int(m.split('-')[0]) for m in work_months})
        adjusted = set()
        for fm in file_months:
            mm = fm.split('-')[1]  # 월 부분만
            for wy in work_years:
                candidate = f"{wy}-{mm}"
                if candidate in work_months:
                    adjusted.add(candidate)
                    break
        if adjusted:
            file_months = adjusted
            # 콘텐츠/트래픽 결과의 file_month도 재조정
            for result_dict in [content_result, traffic_result]:
                for total in result_dict.get('monthly_totals', []):
                    old_fm = total.get('file_month', '')
                    if old_fm:
                        mm = old_fm.split('-')[1]
                        for wy in work_years:
                            candidate = f"{wy}-{mm}"
                            if candidate in work_months:
                                total['file_month'] = candidate
                                break

    all_months = work_months | file_months

    sorted_months = sorted([m for m in all_months if m]) if all_months else []
    current_month = sorted_months[-1] if sorted_months else None
    prev_month = sorted_months[-2] if len(sorted_months) >= 2 else None

    # Current and previous month data
    current_month_data = {}
    prev_month_data = {}

    if work_result.get('monthly_summary'):
        for summary in work_result['monthly_summary']:
            if summary.get('year_month') == current_month:
                current_month_data['work'] = summary
            elif summary.get('year_month') == prev_month:
                prev_month_data['work'] = summary

    # Add content totals (by month if available)
    if content_result.get('monthly_totals'):
        for total in content_result['monthly_totals']:
            if total.get('file_month') == current_month:
                current_month_data['content'] = total
            elif total.get('file_month') == prev_month:
                prev_month_data['content'] = total
        # Fallback to combined total
        if 'content' not in current_month_data and content_result.get('total'):
            current_month_data['content'] = content_result['total']

    # Add traffic totals (by month if available)
    if traffic_result.get('monthly_totals'):
        for total in traffic_result['monthly_totals']:
            if total.get('file_month') == current_month:
                current_month_data['traffic'] = total
            elif total.get('file_month') == prev_month:
                prev_month_data['traffic'] = total
        # Fallback to combined total
        if 'traffic' not in current_month_data and traffic_result.get('total'):
            current_month_data['traffic'] = traffic_result['total']

    # Calculate growth rates
    growth_rate = {}

    # Views growth (content)
    curr_views = current_month_data.get('content', {}).get('total_views', 0)
    prev_views = prev_month_data.get('content', {}).get('total_views', 0)
    if prev_views > 0:
        growth_rate['views'] = ((curr_views - prev_views) / prev_views) * 100

    # Completed videos growth (work)
    curr_completed = current_month_data.get('work', {}).get('completed_count', 0)
    prev_completed = prev_month_data.get('work', {}).get('completed_count', 0)
    if prev_completed > 0:
        growth_rate['completed'] = ((curr_completed - prev_completed) / prev_completed) * 100

    # 영상 종류별 통계 (롱폼/일반 숏폼 등) — 1행 컬럼값 기준
    all_work = work_result.get('all_work', [])

    def get_video_type_stats(work_data, target_month):
        """영상 종류별 계약/완료 건수 (1행 컬럼값 기준)"""
        stats = {}
        for work in work_data:
            if work.get('year_month') != target_month:
                continue
            vt = str(work.get('video_type', '')).strip()
            if not vt or vt == 'nan':
                vt = '기타'
            if vt not in stats:
                stats[vt] = {'contract': 0, 'completed': 0}
            stats[vt]['contract'] += work.get('contract_count', 0)
            stats[vt]['completed'] += work.get('completed_count', 0)
        return stats

    def build_video_list(video_records, target_month):
        """영상 리스트 (편집 종류 == '영상', 계약 월 기준, 업로드 날짜순)"""
        filtered = []
        for v in video_records:
            if v.get('contract_month') != target_month:
                continue
            if v.get('edit_type', '') != '영상':
                continue
            title = re.sub(r'^#\d+\s*', '', v.get('title', '')).strip()
            if not title:
                continue
            filtered.append({
                'title': title,
                'upload_date': v.get('upload_date', ''),
            })
        filtered.sort(key=lambda x: x.get('upload_date') or '9999-99-99')
        return filtered

    # 현재 월, 전월 영상 종류별 통계
    curr_video_type_stats = get_video_type_stats(all_work, current_month)
    prev_video_type_stats = get_video_type_stats(all_work, prev_month)

    # 전체 건수 계산
    total_contract = sum(s['contract'] for s in curr_video_type_stats.values())
    total_completed = sum(s['completed'] for s in curr_video_type_stats.values())
    total_carryover = max(0, total_contract - total_completed)

    prev_total_contract = sum(s['contract'] for s in prev_video_type_stats.values())
    prev_total_completed = sum(s['completed'] for s in prev_video_type_stats.values())
    prev_total_carryover = max(0, prev_total_contract - prev_total_completed)

    # 영상 리스트
    all_video_records = work_result.get('all_videos', [])
    curr_video_list = build_video_list(all_video_records, current_month)
    prev_video_list = build_video_list(all_video_records, prev_month)

    # KPI
    work_summary = current_month_data.get('work', {})
    content_total = current_month_data.get('content', {})
    traffic_total = current_month_data.get('traffic', {})

    # 전월 콘텐츠 데이터
    prev_content_total = prev_month_data.get('content', {})

    kpi = {
        'uploaded_videos': work_summary.get('completed_count', 0),
        'completion_rate': round(work_summary.get('completion_rate', 0), 2),
        'avg_lead_time_days': round(work_summary.get('lead_time_days', 0) or 0, 1),
        'total_views': content_total.get('total_views', 0),
        'total_impressions': content_total.get('total_impressions', 0),
        'avg_ctr': round(content_total.get('avg_ctr', 0), 2),
        'new_subscribers': content_total.get('new_subscribers', 0),
        'views_mom_growth': round(growth_rate.get('views', 0), 2),
        # 영상 종류별 통계
        'contract_count': total_contract,
        'completed_count': total_completed,
        'carryover_count': total_carryover,  # 이월 건수
        # 전월 데이터
        'prev_total_views': prev_content_total.get('total_views', 0),
        'prev_total_impressions': prev_content_total.get('total_impressions', 0),
        'prev_new_subscribers': prev_content_total.get('new_subscribers', 0),
        'prev_contract_count': prev_total_contract,
        'prev_completed_count': prev_total_completed,
        'prev_carryover_count': prev_total_carryover
    }

    # 월별 TOP5 데이터 추출
    monthly_top5 = content_result.get('monthly_top5', {})
    monthly_traffic = traffic_result.get('monthly_traffic', {})

    # 당월/전월 top5_videos
    curr_top5_videos = monthly_top5.get(current_month, content_result.get('top5_videos', []))
    prev_top5_videos = monthly_top5.get(prev_month, [])

    # 당월/전월 traffic_by_source
    curr_traffic = monthly_traffic.get(current_month, traffic_result.get('by_source', []))
    prev_traffic = monthly_traffic.get(prev_month, [])

    # Tables
    tables = {
        'top5_videos': curr_top5_videos,
        'prev_top5_videos': prev_top5_videos,  # 전월 TOP5 동영상
        'traffic_by_source': curr_traffic,
        'prev_traffic_by_source': prev_traffic,  # 전월 트래픽 소스
        'work_summary': work_result.get('monthly_summary', []),
        'all_videos': work_result.get('all_videos', []),
        # 영상 종류별 통계 (롱폼/일반 숏폼 등)
        'video_type_stats': curr_video_type_stats,
        'prev_video_type_stats': prev_video_type_stats,
        # 영상 리스트 (편집 종류 == "영상"만, 업로드 날짜순)
        'video_list': curr_video_list,
        'prev_video_list': prev_video_list,
        # 월별 데이터 (상세)
        'monthly_top5': monthly_top5,
        'monthly_traffic': monthly_traffic
    }

    # Charts
    charts = {
        'monthly_trend': work_result.get('monthly_summary', []),
        'monthly_content_totals': content_result.get('monthly_totals', []),
        'monthly_traffic_totals': traffic_result.get('monthly_totals', [])
    }

    # Clean data
    # 거래처명 수집 (불일치 감지용)
    clinic_names = work_result.get('clinic_names', [])
    clinic_name = clinic_names[0] if clinic_names else None

    clean_data = {
        'work': work_result,
        'content': content_result,
        'traffic': traffic_result,
        'clinic_name': clinic_name,
        'clinic_names': clinic_names
    }

    return {
        'department': '영상팀',
        'month': current_month,
        'prev_month': prev_month,
        'current_month_data': current_month_data,
        'prev_month_data': prev_month_data,
        'growth_rate': growth_rate,
        'kpi': kpi,
        'tables': tables,
        'charts': charts,
        'clean_data': clean_data
    }
