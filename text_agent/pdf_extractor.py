import fitz  # PyMuPDF


def extract_text_from_pdf(pdf_path: str) -> tuple[str | None, str | None]:
    """使用 PyMuPDF（fitz）从 PDF 文件中提取全文文本。

    逐页提取文本，过滤空白页，页间以双换行分隔以保留段落结构。
    提取结果保留原始排版顺序，不做 OCR（不支持纯图像 PDF）。

    参数：
        pdf_path : PDF 文件的绝对路径

    返回 (text, None) 表示成功，text 为完整论文全文字符串；
    返回 (None, 错误描述) 表示失败（文件不存在、无法解析、无可提取文本等）。
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return None, f'PDF 文件打开失败（路径：{pdf_path}）：{e}'

    try:
        pages = []
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text()
            # 过滤空白页（仅有空白字符的页不计入）
            if text.strip():
                pages.append(text)
        doc.close()
    except Exception as e:
        doc.close()
        return None, f'PDF 文本提取过程出错：{e}'

    if not pages:
        return None, f'PDF 文件无可提取文本（可能为纯图像 PDF）：{pdf_path}'

    # 页间以双换行分隔，保留段落结构
    full_text = '\n\n'.join(pages)
    return full_text, None
