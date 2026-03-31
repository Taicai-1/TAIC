import io
import csv
import pandas as pd
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from tabulate import tabulate
from datetime import datetime
import re
import json
from typing import Dict, List, Any, Optional, Tuple

class FileGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        
    def detect_generation_request(self, question: str, answer: str) -> Dict[str, Any]:
        """Détecte si l'utilisateur demande la génération d'un fichier"""
        question_lower = question.lower()
        answer_lower = answer.lower()
        
        # Mots-clés pour CSV/Tableau
        csv_keywords = ['tableau', 'récapitulatif', 'récap', 'csv', 'export', 'données', 'liste', 'synthèse']
        
        # Mots-clés pour PDF
        pdf_keywords = ['rapport', 'document', 'pdf', 'présentation', 'analyse', 'fiche']
        
        # Détecter les tableaux dans la réponse
        has_table_structure = self._detect_table_in_text(answer)
        
        result = {
            'generate_csv': any(keyword in question_lower for keyword in csv_keywords) or has_table_structure,
            'generate_pdf': any(keyword in question_lower for keyword in pdf_keywords),
            'has_table': has_table_structure,
            'table_data': None,
            'formatted_answer': answer
        }
        
        if has_table_structure:
            result['table_data'] = self._extract_table_from_text(answer)
            result['formatted_answer'] = self._format_answer_with_table(answer, result['table_data'])
            
        return result
    
    def _detect_table_in_text(self, text: str) -> bool:
        """Détecte si le texte contient des données tabulaires"""
        # Recherche de patterns de tableaux
        patterns = [
            r'(\w+)\s*:\s*\d+',  # "Ventes: 1000"
            r'\|\s*\w+\s*\|\s*\w+\s*\|',  # Format markdown table
            r'\d+\.\s+\w+',  # Liste numérotée
            r'-\s+\w+\s*:\s*',  # Liste avec tirets et valeurs
        ]
        
        for pattern in patterns:
            if len(re.findall(pattern, text)) >= 3:  # Au moins 3 occurrences
                return True
        return False
    
    def _extract_table_from_text(self, text: str) -> Optional[List[List[str]]]:
        """Extrait les données tabulaires du texte"""
        lines = text.split('\n')
        table_data = []
        seen_pairs = set()  # Pour éviter les doublons
        
        # Recherche de patterns de données structurées
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Pattern "Label: Valeur"
            match = re.match(r'([^:]+):\s*(.+)', line)
            if match:
                label, value = match.groups()
                label = label.strip()
                value = value.strip()
                
                # Nettoyer les numéros en début de label
                label = re.sub(r'^\d+\.\s*', '', label)
                
                # Éviter les doublons
                pair_key = (label.lower(), value.lower())
                if pair_key not in seen_pairs and len(value) > 10:  # Valeurs substantielles seulement
                    table_data.append([label, value])
                    seen_pairs.add(pair_key)
            
            # Pattern "- Label: Valeur"
            match = re.match(r'-\s+([^:]+):\s*(.+)', line)
            if match:
                label, value = match.groups()
                label = label.strip()
                value = value.strip()
                
                pair_key = (label.lower(), value.lower())
                if pair_key not in seen_pairs and len(value) > 10:
                    table_data.append([label, value])
                    seen_pairs.add(pair_key)
                
            # Pattern numéroté "1. Label: Valeur"
            match = re.match(r'\d+\.\s+([^:]+):\s*(.+)', line)
            if match:
                label, value = match.groups()
                label = label.strip()
                value = value.strip()
                
                pair_key = (label.lower(), value.lower())
                if pair_key not in seen_pairs and len(value) > 10:
                    table_data.append([label, value])
                    seen_pairs.add(pair_key)
        
        return table_data if len(table_data) >= 2 else None
    
    def _format_answer_with_table(self, answer: str, table_data: List[List[str]]) -> str:
        """Formate la réponse avec un tableau lisible"""
        if not table_data:
            return answer
            
        # Créer un tableau formaté avec tabulate - format plus propre
        table_str = tabulate(table_data, headers=['Élément', 'Valeur'], tablefmt='simple', maxcolwidths=[30, 80])
        
        # Remplacer les données brutes par le tableau formaté
        formatted_answer = answer
        for row in table_data:
            # Enlever les patterns originaux
            patterns_to_remove = [
                f"{row[0]}: {row[1]}",
                f"- {row[0]}: {row[1]}",
                f"{row[0]}: {row[1]}"
            ]
            for pattern in patterns_to_remove:
                formatted_answer = formatted_answer.replace(pattern, "")
        
        # Ajouter le tableau formaté
        formatted_answer = formatted_answer.strip() + f"\n\n{table_str}"
        
        return formatted_answer
    
    def generate_csv(self, data: List[List[str]], filename: str = None) -> io.BytesIO:
        """Génère un fichier CSV à partir des données - optimisé"""
        if not filename:
            filename = f"rapport_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
        output = io.BytesIO()
        
        # Utiliser pandas pour une génération plus rapide
        try:
            df = pd.DataFrame(data, columns=['Élément', 'Valeur'])
            csv_string = df.to_csv(index=False, encoding='utf-8')
            output.write(csv_string.encode('utf-8'))
        except:
            # Fallback vers la méthode manuelle si pandas échoue
            output_str = io.StringIO()
            writer = csv.writer(output_str)
            writer.writerow(['Élément', 'Valeur'])
            writer.writerows(data)
            output.write(output_str.getvalue().encode('utf-8'))
        
        output.seek(0)
        return output
    
    def generate_pdf(self, title: str, content: str, table_data: List[List[str]] = None) -> io.BytesIO:
        """Génère un PDF avec le contenu et les tableaux"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        story = []
        
        # Styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            textColor=colors.darkblue
        )
        
        # Titre
        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 12))
        
        # Date
        date_str = datetime.now().strftime("%d/%m/%Y à %H:%M")
        story.append(Paragraph(f"<i>Généré le {date_str}</i>", self.styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Contenu principal
        paragraphs = content.split('\n\n')
        for para in paragraphs:
            if para.strip():
                story.append(Paragraph(para.strip(), self.styles['Normal']))
                story.append(Spacer(1, 12))
        
        # Tableau si présent
        if table_data:
            story.append(Spacer(1, 20))
            story.append(Paragraph("<b>Données détaillées:</b>", self.styles['Heading2']))
            story.append(Spacer(1, 12))
            
            # Ajouter en-têtes si nécessaire
            if len(table_data[0]) == 2:
                table_data = [['Élément', 'Valeur']] + table_data
            
            table = Table(table_data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            story.append(table)
        
        doc.build(story)
        buffer.seek(0)
        return buffer
    
    def create_sample_data(self, agent_type: str) -> List[List[str]]:
        """Crée des données d'exemple selon le type d'agent"""
        sample_data = {
            'sales': [
                ['Prospects contactés', '45'],
                ['Rendez-vous obtenus', '12'],
                ['Ventes réalisées', '8'],
                ['Chiffre d\'affaires', '25 000€'],
                ['Taux de conversion', '17.8%']
            ],
            'marketing': [
                ['Campagnes lancées', '3'],
                ['Impressions', '15 420'],
                ['Clics', '892'],
                ['Taux de clic', '5.8%'],
                ['Leads générés', '34']
            ],
            'hr': [
                ['Candidatures reçues', '28'],
                ['Entretiens menés', '12'],
                ['Offres envoyées', '5'],
                ['Embauches', '3'],
                ['Délai moyen', '15 jours']
            ],
            'purchase': [
                ['Fournisseurs contactés', '8'],
                ['Devis reçus', '6'],
                ['Commandes passées', '4'],
                ['Économies réalisées', '2 300€'],
                ['Délai moyen livraison', '7 jours']
            ]
        }
        
        return sample_data.get(agent_type, sample_data['sales'])
