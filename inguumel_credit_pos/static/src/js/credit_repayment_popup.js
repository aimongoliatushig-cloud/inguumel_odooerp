/** @odoo-module */
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class CreditRepaymentPopup extends Component {
    static template = "inguumel_credit_pos.CreditRepaymentPopup";
    static props = {
        partnerId: { type: Number, optional: true },
        sessionId: { type: Number },
        close: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loans: [],
            selectedLoanId: null,
            amount: "",
            date: "",
            error: "",
            loading: true,
        });
        this.loadLoans();
    }

    async loadLoans() {
        if (!this.props.partnerId) {
            this.state.loading = false;
            this.state.error = "Харилцагч сонгоно уу";
            return;
        }
        try {
            const loans = await this.orm.call(
                "pos.session",
                "get_credit_loans",
                [this.props.sessionId, this.props.partnerId]
            );
            this.state.loans = loans || [];
            if (this.state.loans.length > 0 && !this.state.selectedLoanId) {
                this.state.selectedLoanId = this.state.loans[0].id;
            }
        } catch (e) {
            this.state.error = "Зээлийн жагсаалт ачааллахад алдаа гарлаа";
        }
        this.state.loading = false;
    }

    get selectedLoan() {
        if (!this.state.selectedLoanId) return null;
        return this.state.loans.find((l) => l.id === this.state.selectedLoanId) || null;
    }

    onConfirm() {
        this.state.error = "";
        if (!this.state.date || !this.state.date.trim()) {
            this.state.error = "Төлөх огноо оруулна уу";
            return;
        }
        const amt = parseFloat(this.state.amount);
        if (isNaN(amt) || amt <= 0) {
            this.state.error = "Зээлийн төлөлтийн дүн оруулна уу";
            return;
        }
        if (!this.state.selectedLoanId) {
            this.state.error = "Зээл сонгоно уу";
            return;
        }
        this.orm
            .call("pos.session", "register_credit_repayment", [
                this.props.sessionId,
                this.state.selectedLoanId,
                amt,
                this.state.date.trim(),
            ])
            .then(() => {
                this.props.close();
            })
            .catch((err) => {
                const msg = err && err.data && err.data.message;
                this.state.error = msg || "Үлдэгдлээс их дүн оруулах боломжгүй";
            });
    }

    onCancel() {
        this.props.close();
    }
}
