from django.contrib import admin

from .models import (Announcement, Applicant, Assignment, AttendanceRecord, AuditLog,
                     Book, CalendarEvent, Certificate, ClassRoom, ConcessionRequest,
                     DisciplineRecord, HostelRoom,
                     Exam, ExamRoom, ExamSchedule, Expense,
                     FeeChallan, FeePayment, InventoryItem, IssuedBook, LeaveRequest,
                     Mark, Material, OnlinePayment, Payslip,
                     Profile, Question, Quiz, QuizAttempt, School, Seat, SmsMessage,
                     Staff, StaffAttendance, Student, Subject, Submission,
                     TeachingAssignment, TimetableSlot,
                     TransportRoute, Visitor)

for model in (School, ClassRoom, Student, Profile, Announcement, Subject, Exam,
              ExamRoom, ExamSchedule, Seat,
              AttendanceRecord, Mark, FeePayment, FeeChallan, ConcessionRequest,
              OnlinePayment, Expense, Applicant, SmsMessage,
              TransportRoute, Book, IssuedBook, Staff, StaffAttendance, LeaveRequest,
              Payslip, Certificate, CalendarEvent,
              InventoryItem, Visitor, Material, TimetableSlot, Assignment,
              Submission, Quiz, Question, QuizAttempt, TeachingAssignment, HostelRoom,
              DisciplineRecord, AuditLog):
    admin.site.register(model)