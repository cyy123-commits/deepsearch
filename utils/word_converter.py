import logging
import os
from pathlib import Path
import time

try:
    import markdown #markdown-》html
    import win32com.client#来自pywin32 作用Microsoft Word Excel PowerPoint
    import pythoncom #初始化com线程环境，COM是windows的组件对象模型，必须初始化才能使用com对象
except ImportError:
    pass


def convert_md_to_pdf_via_word(md_abs_path: Path, pdf_abs_path: Path) -> str:
    """
    使用 Microsoft Word COM 接口将 Markdown 转换为 PDF。
    依赖：pywin32, markdown
    """
    temp_html_path = md_abs_path.with_suffix('.temp.html')#转换成临时html，使word直接解析
    word_app = None

    try:
        # 1. MD 转 HTML
        with open(md_abs_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        #调用markdown将md转html，支持表格和代码块
        html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])
        html_content = f"""
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: "Microsoft YaHei", "SimHei", sans-serif; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid black; padding: 8px; }}
                pre {{ background-color: #f5f5f5; padding: 10px; border-radius: 4px; }}
                code {{ font-family: "Consolas", "Monaco", monospace; }}
            </style>
        </head>
        <body>
            {html_body}
        </body>
        </html>
        """

        with open(temp_html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # 2. 调用 Word COM
        pythoncom.CoInitialize()#初始化com
        word_app = win32com.client.Dispatch('Word.Application')#启动 Microsoft Word，后台运行
        word_app.Visible = False#不弹窗口
        word_app.DisplayAlerts = False#不谈提示框

        doc = word_app.Documents.Open(str(temp_html_path.resolve()))
        doc.SaveAs(str(pdf_abs_path.resolve()), FileFormat=17)  # wdFormatPDF = 17
        doc.Close(SaveChanges=0)

        if pdf_abs_path.exists():
            return f"成功转换: {pdf_abs_path} (Word引擎)"
        else:
            return f"转换完成但未生成文件: {pdf_abs_path}"

    except ImportError:
        return "缺少依赖库，请安装: pip install pywin32 markdown"
    except Exception as e:
        logging.error(f"Word转换PDF失败: {e}", exc_info=True)
        return f"转换失败: {str(e)}"

    finally:
        # 3. 资源清理
        if word_app:
            try:
                word_app.Quit()
            except:
                pass

        if temp_html_path.exists():
            try:
                temp_html_path.unlink()
            except:
                pass

        try:
            pythoncom.CoUninitialize()
        except:
            pass